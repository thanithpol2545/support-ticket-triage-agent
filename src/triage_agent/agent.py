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
from .policy import (
    _access_problem,
    _payment_failure,
    finalize,
    reports_dark_mode_scheduling,
    reports_http_500,
    reports_refund_dispute,
    risk_signals,
)
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
        refund_dispute = billing and reports_refund_dispute(ticket)
        billing_issues = ["refund_dispute" if refund_dispute else "repeated_charges_reported"]
        billing_reason = "Refund dispute reported" if refund_dispute else "Repeated charges reported"
        pro_upgrade = any("upgrade to pro" in message.text.lower() for message in ticket.messages)
        if pro_upgrade and _payment_failure(ticket):
            billing_issues.insert(0, "failed_upgrade")
        if billing:
            tools.call("check_billing_status", {"customer_id": ticket.customer.customer_id})
        if outage:
            tools.call("check_system_status", {"region": ticket.customer.region or "Unknown"})
            issues = ["access_failure"]
            if reports_http_500(ticket):
                issues.insert(0, "http_500")
            reasons = ["Multiple users reported unable to access the service"]
            if billing:
                issues.extend(billing_issues)
                reasons.append(billing_reason)
            articles = {"KB-001", "KB-002"} if billing else {"KB-002"}
            product = "Enterprise platform" if ticket.customer.plan.casefold() == "enterprise" else "Application"
            proposal = AgentProposal(urgency="critical", product=product, issue_types=issues,
                sentiment="frustrated", action="escalate_to_human", assigned_team="Infrastructure / On-call",
                summary="Customer reports that multiple users cannot access the service.",
                reasons=reasons, kb_article_ids=[r for r in refs if r in articles],
                draft_response="We are escalating the reported service failure for investigation.",
                uncertainties=[])
        elif billing:
            proposal = AgentProposal(urgency="high", product="Pro upgrade" if pro_upgrade else "Billing", issue_types=billing_issues,
                sentiment="angry", action="escalate_to_human", assigned_team="Billing Support",
                summary=f"{billing_reason} by the customer.",
                reasons=[billing_reason], kb_article_ids=[r for r in refs if r == "KB-001"],
                draft_response="We are escalating your billing issue for review.", uncertainties=["Bank-side settlement unverified"])
        elif dark_bug:
            issues = ["appearance_bug"]
            if reports_dark_mode_scheduling(ticket):
                issues.append("feature_request")
            product = "Pro application" if ticket.customer.plan.casefold() == "pro" else "Application appearance"
            proposal = AgentProposal(urgency="medium", product=product, issue_types=issues,
                sentiment="concerned", action="route_to_specialist", assigned_team="Product Support",
                summary="Customer reports that dark mode does not work as expected.",
                reasons=["Customer-reported appearance problem"], kb_article_ids=[r for r in refs if r == "KB-003"],
                draft_response="We will ask Product Support to investigate the appearance setting.", uncertainties=[])
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
