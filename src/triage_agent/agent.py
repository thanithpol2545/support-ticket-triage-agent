"""GPT ticket triage with a bounded Responses API function-calling loop."""
from __future__ import annotations

import json
import os
from importlib.resources import files
from typing import Any

from pydantic import ValidationError

from .models import AgentProposal, PROPOSAL_JSON_SCHEMA, Ticket, TriageAudit, TriageResult
from .policy import finalize
from .tools import TOOL_SCHEMAS, ToolRegistry, load_data


class AgentExecutionError(RuntimeError):
    """A live agent run could not complete or validate safely."""


def load_tickets() -> list[Ticket]:
    return [Ticket.model_validate(x) for x in load_data("tickets.json")]


def _instructions() -> str:
    return files("triage_agent").joinpath("prompts", "system.md").read_text(encoding="utf-8")


class GPTTriageAgent:
    """OpenAI Responses API agent; injectable client allows offline integration tests."""

    def __init__(self, client: Any = None, model: str | None = None, max_rounds: int = 8):
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        self.max_rounds = max_rounds
        if client is None:
            if not os.environ.get("OPENAI_API_KEY", "").strip():
                raise AgentExecutionError(
                    "OPENAI_API_KEY is required. Set $env:OPENAI_API_KEY in PowerShell "
                    "or export OPENAI_API_KEY in Bash. See README.md for masked key entry."
                )
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise AgentExecutionError("OpenAI SDK missing; install with: pip install -e '.[dev]'") from exc
            client = OpenAI(timeout=35.0, max_retries=2)
        self.client = client

    def run(self, ticket: Ticket) -> TriageResult:
        return self.run_with_audit(ticket).result

    def run_with_audit(self, ticket: Ticket) -> TriageAudit:
        tools = ToolRegistry(ticket)
        history: list[Any] = [{"role": "user", "content": json.dumps(ticket.model_dump(), ensure_ascii=False)}]
        # Forced tool choices guarantee both mandated tools are truly called, not just named in JSON.
        forced = ["get_customer_history", "search_knowledge_base"]
        for round_index in range(self.max_rounds):
            choice: Any = ( {"type": "function", "name": forced[round_index]}
                            if round_index < len(forced) else "auto" )
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=_instructions(),
                    input=history,
                    tools=TOOL_SCHEMAS,
                    tool_choice=choice,
                    parallel_tool_calls=False,
                    text={"format": {"type": "json_schema", "name": "triage_result", "strict": True,
                                     "schema": PROPOSAL_JSON_SCHEMA}},
                    store=False,
                )
            except Exception as exc:
                raise AgentExecutionError(
                    f"OpenAI response failed ({type(exc).__name__}). "
                    "Check connectivity, credentials, and model availability."
                ) from None

            if getattr(response, "status", "completed") not in (None, "completed"):
                raise AgentExecutionError("OpenAI did not complete the response")
            output = list(getattr(response, "output", []) or [])
            calls = [item for item in output if getattr(item, "type", "") == "function_call"]
            if round_index < 2 and (len(calls) != 1 or calls[0].name != forced[round_index]):
                raise AgentExecutionError(f"Required tool not called: {forced[round_index]}")

            history.extend(output)
            if calls:
                for item in calls:
                    try:
                        arguments = json.loads(item.arguments)
                        if not isinstance(arguments, dict):
                            arguments = {}
                    except (ValueError, TypeError):
                        arguments = {}
                    result = tools.call(item.name, arguments)
                    if round_index < 2 and not tools.trace[-1].ok:
                        raise AgentExecutionError(f"Required tool failed: {item.name}: {result.get('error')}")
                    history.append({"type": "function_call_output", "call_id": item.call_id,
                                    "output": json.dumps(result, ensure_ascii=False)})
                continue

            content = getattr(response, "output_text", None)
            if not isinstance(content, str) or not content.strip():
                raise AgentExecutionError("Model did not return a structured final answer")
            try:
                proposal = AgentProposal.model_validate_json(content)
            except ValidationError:
                raise AgentExecutionError("Invalid model output schema") from None
            return TriageAudit(
                configured_model=self.model,
                response_model=getattr(response, "model", None),
                proposal=proposal,
                result=finalize(ticket, proposal, tools),
            )
        raise AgentExecutionError("Maximum tool rounds exceeded; no unsafe auto-response was produced")
