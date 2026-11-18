"""One GPT agent with a bounded Responses API function-calling loop.

A separate deterministic demo mode exercises mocks/policy without claiming GPT usage.
"""
from __future__ import annotations

import json
import os
from importlib.resources import files
from typing import Any

from pydantic import ValidationError

from .models import AgentProposal, PROPOSAL_JSON_SCHEMA, Ticket, TriageResult
from .policy import finalize, risk_signals, _access_problem, _payment_failure
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
            if not os.environ.get("OPENAI_API_KEY"):
                raise AgentExecutionError("OPENAI_API_KEY is required for --mode live. Use --mode demo without a key.")
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise AgentExecutionError("OpenAI SDK missing; install with: pip install -e '.[dev]'") from exc
            client = OpenAI(timeout=35.0, max_retries=2)
        self.client = client

    def run(self, ticket: Ticket) -> TriageResult:
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
            except ValidationError as exc:
                raise AgentExecutionError(f"Invalid model output schema: {exc}") from exc
            return finalize(ticket, proposal, tools, "live_gpt")
        raise AgentExecutionError("Maximum tool rounds exceeded; no unsafe auto-response was produced")


class DemoTriageAgent:
    """Offline deterministic example; expressly NOT an OpenAI model run."""

    def run(self, ticket: Ticket) -> TriageResult:
        tools = ToolRegistry(ticket)
        tools.call("get_customer_history", {"customer_id": ticket.customer.customer_id})
        search = " ".join(x.text for x in ticket.messages)
        tools.call("search_knowledge_base", {"query": search[:2000]})
        outage, billing, dark_bug = risk_signals(ticket)
        refs = sorted(tools.valid_article_ids())
        if billing:
            tools.call("check_billing_status", {"customer_id": ticket.customer.customer_id})
            proposal = AgentProposal(urgency="high", product="Pro upgrade", issue_types=["failed_upgrade", "repeated_charges_reported"],
                sentiment="angry", action="escalate_to_human", assigned_team="Billing Support",
                summary="Customer reports repeated charges and no access to Pro after upgrade attempts.",
                reasons=["Multiple charges reported", "Time-sensitive Pro access"], kb_article_ids=[r for r in refs if r == "KB-001"],
                draft_response="We are escalating your billing issue for review.", uncertainties=["Bank-side settlement unverified"])
        elif outage:
            tools.call("check_system_status", {"region": ticket.customer.region or "Asia"})
            proposal = AgentProposal(urgency="critical", product="Enterprise platform", issue_types=["http_500", "access_failure"],
                sentiment="frustrated", action="escalate_to_human", assigned_team="Infrastructure / On-call",
                summary="Thai enterprise customer reports multi-user access failure and a high-stakes demo.",
                reasons=["HTTP 500", "Multiple coworkers affected", "Potential business impact"], kb_article_ids=[r for r in refs if r == "KB-002"],
                draft_response="We are escalating the reported service failure for investigation.", uncertainties=["Regional scope unconfirmed"])
        elif dark_bug:
            proposal = AgentProposal(urgency="medium", product="Pro application", issue_types=["appearance_bug", "feature_request"],
                sentiment="concerned", action="route_to_specialist", assigned_team="Product Support",
                summary="System Default is not following device dark appearance; customer also suggests scheduling.",
                reasons=["Reproducible appearance problem", "Separate feature request"], kb_article_ids=[r for r in refs if r == "KB-003"],
                draft_response="We will ask Product Support to investigate the appearance setting.", uncertainties=["Scheduled mode not verified"])
        elif _access_problem(ticket) or _payment_failure(ticket):
            access = _access_problem(ticket)
            proposal = AgentProposal(urgency="medium", product="Application", issue_types=["access_failure" if access else "failed_payment"],
                sentiment="concerned", action="route_to_specialist", assigned_team="Technical Support" if access else "Billing Support",
                summary="Customer reports an access problem or an unsuccessful transaction.",
                reasons=["Diagnostic review is required"], kb_article_ids=refs,
                draft_response="A specialist will investigate; the cause is not yet known.",
                uncertainties=["Underlying failure unverified"])
        else:
            proposal = AgentProposal(urgency="low", product="General application", issue_types=["general_question"],
                sentiment="neutral", action="auto_respond", assigned_team=None,
                summary="General support question requiring documentation.", reasons=["No verified high-impact signals"],
                kb_article_ids=refs, draft_response="Please refer to the cited help article.", uncertainties=[])
        return finalize(ticket, proposal, tools, "demo_rules")
