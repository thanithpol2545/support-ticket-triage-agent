"""Optional Typhoon API evaluation adapter (OpenAI-compatible Chat Completions).

The Ooca submission's required GPT agent remains in agent.py. This adapter is
for development evaluation against a second provider, not a replacement GPT.
Secrets are read from environment only and never written into traces.
"""
from __future__ import annotations

import json
import os
from typing import Any

from pydantic import ValidationError

from .agent import AgentExecutionError, _instructions
from .models import AgentProposal, Ticket, TriageResult
from .policy import finalize
from .tools import TOOL_SCHEMAS, ToolRegistry


def _chat_tool_schemas() -> list[dict[str, Any]]:
    """Convert OpenAI Responses tool schemas into Chat Completions function tools."""
    return [
        {"type": "function", "function": {
            "name": item["name"],
            "description": item["description"],
            "parameters": item["parameters"],
        }}
        for item in TOOL_SCHEMAS
    ]


class TyphoonTriageAgent:
    """A separate provider adapter with bounded calls and schema validation."""

    def __init__(self, client: Any = None, model: str | None = None, max_rounds: int = 8):
        self.model = model or os.getenv("TYPHOON_MODEL", "typhoon-v2.5-30b-a3b-instruct")
        self.max_rounds = max_rounds
        if client is None:
            key = os.getenv("TYPHOON_API_KEY")
            if not key:
                raise AgentExecutionError(
                    "TYPHOON_API_KEY is required for --mode typhoon. "
                    "Set it as an environment variable; do not commit it."
                )
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise AgentExecutionError("OpenAI SDK missing: pip install -e '.[dev]'") from exc
            client = OpenAI(
                api_key=key,
                base_url="https://api.opentyphoon.ai/v1",
                timeout=35.0,
                max_retries=1,
            )
        self.client = client

    def run(self, ticket: Ticket) -> TriageResult:
        registry = ToolRegistry(ticket)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _instructions() + "\nReturn exactly one JSON object, no Markdown fences."},
            {"role": "user", "content": json.dumps(ticket.model_dump(), ensure_ascii=False)},
        ]
        required = ["get_customer_history", "search_knowledge_base"]
        for round_index in range(self.max_rounds):
            tool_choice: Any = (
                {"type": "function", "function": {"name": required[round_index]}}
                if round_index < len(required) else "auto"
            )
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=_chat_tool_schemas(),
                    tool_choice=tool_choice,
                    temperature=0,
                    max_tokens=2400,
                )
            except Exception as exc:
                # Don't echo provider exceptions; some SDKs include request metadata.
                raise AgentExecutionError(
                    f"Typhoon request failed ({type(exc).__name__}). "
                    "Check network connectivity, key permissions, and model availability."
                ) from None

            choices = getattr(response, "choices", None)
            if not choices:
                raise AgentExecutionError("Typhoon returned no completion choices")
            choice = choices[0]
            message = choice.message
            calls = list(getattr(message, "tool_calls", None) or [])
            if round_index < len(required) and (
                len(calls) != 1 or calls[0].function.name != required[round_index]
            ):
                raise AgentExecutionError(f"Required tool not called: {required[round_index]}")

            if calls:
                assistant_message = {"role": "assistant", "content": getattr(message, "content", None),
                    "tool_calls": [{"id": item.id, "type": "function", "function": {
                        "name": item.function.name, "arguments": item.function.arguments,
                    }} for item in calls]}
                messages.append(assistant_message)
                for item in calls:
                    try:
                        arguments = json.loads(item.function.arguments)
                        if not isinstance(arguments, dict):
                            arguments = {}
                    except (ValueError, TypeError):
                        arguments = {}
                    result = registry.call(item.function.name, arguments)
                    if round_index < len(required) and not registry.trace[-1].ok:
                        raise AgentExecutionError(f"Required tool failed: {item.function.name}")
                    messages.append({"role": "tool", "tool_call_id": item.id,
                                     "content": json.dumps(result, ensure_ascii=False)})
                continue

            if getattr(choice, "finish_reason", None) == "length":
                raise AgentExecutionError("Typhoon output truncated by token limit")
            content = getattr(message, "content", None)
            if not isinstance(content, str) or not content.strip():
                raise AgentExecutionError("Typhoon did not produce a JSON proposal")
            try:
                proposal = AgentProposal.model_validate_json(content)
            except (ValidationError, ValueError) as exc:
                raise AgentExecutionError("Typhoon output failed schema validation") from exc
            return finalize(ticket, proposal, registry, "live_typhoon")
        raise AgentExecutionError("Typhoon maximum tool rounds exceeded")
