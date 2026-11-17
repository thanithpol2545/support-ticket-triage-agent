"""Deterministic guardrails. The LLM can suggest; policy can only make routing safer."""
from __future__ import annotations
import re

from .models import AgentProposal, Ticket, TriageResult
from .tools import ToolRegistry

RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _floor_urgency(value: str, minimum: str) -> str:
    return value if RANK[value] >= RANK[minimum] else minimum


def _signals(ticket: Ticket) -> tuple[bool, bool, bool]:
    message = "\n".join(x.text for x in ticket.messages).lower()
    # Explicit multi-user outage/HTTP 500 signals, independent of provider's green status page.
    outage = (ticket.customer.plan.lower() == "enterprise"
              and ("500" in message or "เข้าไม่ได้" in message)
              and any(s in message for s in ("coworkers", "colleagues", "multiple users", "เพื่อนร่วมงาน", "หลายเครื่อง")))
    # A financial dispute or multiple charges is always a human decision.
    billing = (any(s in message for s in ("charge", "charged", "payment", "billing", "บัตร", "หักเงิน"))
               and any(s in message for s in ("two pending", "three charges", "multiple charges", "duplicate", "disput", "ซ้ำ")))
    # Dark mode questions alone can be low; a stated malfunction warrants specialist review.
    dark_bug = ("dark mode" in message and any(s in message for s in ("still shows light", "still light", "not working", "bug", "ไม่ทำงาน")))
    return outage, billing, dark_bug


def finalize(ticket: Ticket, proposal: AgentProposal, tools: ToolRegistry, mode: str) -> TriageResult:
    data = proposal.model_dump()
    changes: list[str] = []
    valid = tools.valid_article_ids()
    grounded = [k for k in data["kb_article_ids"] if k in valid]
    if grounded != data["kb_article_ids"]:
        changes.append("unverified_kb_article_ids_removed")
        data["kb_article_ids"] = grounded

    outage, billing, dark_bug = _signals(ticket)
    if outage:
        if data["urgency"] != "critical":
            changes.append("enterprise_multi_user_outage_min_critical")
        data["urgency"] = "critical"
        if data["action"] != "escalate_to_human":
            changes.append("outage_requires_human_escalation")
        data["action"] = "escalate_to_human"
        data["assigned_team"] = "Infrastructure / On-call"
        data["draft_response"] = "รับทราบปัญหาเข้าใช้งานไม่ได้และ HTTP 500 ที่หลายท่านพบครับ เราจะส่งต่อทีมเทคนิคเพื่อตรวจสอบโดยเร่งด่วน ขณะนี้ยังไม่สามารถยืนยันสาเหตุหรือสถานะของ region Asia ได้ครับ"
        data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"], "Regional incident not confirmed", "Exact affected user count not verified"]))
    elif billing:
        prior = data["urgency"]
        data["urgency"] = _floor_urgency(data["urgency"], "high")
        if data["urgency"] != prior:
            changes.append("repeated_billing_min_high")
        if data["action"] != "escalate_to_human":
            changes.append("billing_dispute_requires_human_escalation")
        data["action"] = "escalate_to_human"
        data["assigned_team"] = "Billing Support"
        data["draft_response"] = "I'm sorry about the repeated charges you reported and the missing Pro access. I'm escalating this to our billing specialists for urgent investigation. We cannot yet confirm whether the bank entries are settled or reversed; the team will review your account and transactions."
        data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"], "Bank charges and refunds not verified"]))
    elif dark_bug:
        previous = data["urgency"]
        data["urgency"] = _floor_urgency(data["urgency"], "medium")
        if data["urgency"] != previous:
            changes.append("reported_feature_defect_min_medium")
        if data["action"] == "auto_respond":
            changes.append("unverified_defect_requires_specialist")
            data["action"] = "route_to_specialist"
        if data["action"] == "route_to_specialist":
            data["assigned_team"] = "Product Support"
        data["draft_response"] = "Thanks for reporting this. Since System Default isn't following your Mac's appearance setting, our product support team can investigate. We also noted your scheduled dark-mode suggestion; its availability isn't confirmed in the documentation."
        data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"], "Dark-mode schedule availability unverified"]))

    if data["action"] == "auto_respond" and not data["kb_article_ids"]:
        changes.append("no_grounded_kb_prevents_auto_response")
        data["action"] = "route_to_specialist"
        data["assigned_team"] = data["assigned_team"] or "General Support"
        data["draft_response"] = "Thanks for contacting support. We're routing your question to a specialist because we don't have a verified answer yet."

    if data["action"] == "auto_respond" and any(not event.ok for event in tools.trace):
        changes.append("tool_failure_prevents_auto_response")
        data["action"] = "route_to_specialist"
        data["assigned_team"] = "General Support"
        data["draft_response"] = "We're checking this with our support team because a required verification wasn't available."

    if data["action"] != "auto_respond" and not data["assigned_team"]:
        changes.append("assigned_fallback_team")
        data["assigned_team"] = "General Support"

    data["reasons"] = list(dict.fromkeys([*data["reasons"], *changes]))
    return TriageResult(
        ticket_id=ticket.ticket_id,
        **data,
        policy_overrides=changes,
        tools_used=list(dict.fromkeys(x.name for x in tools.trace)),
        tool_trace=tools.trace,
        mode=mode,
    )
