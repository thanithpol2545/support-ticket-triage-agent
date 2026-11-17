"""Deterministic safety rules around an untrusted model proposal.

This is a conservative backstop, not a complete natural-language classifier. It
catches clear high-risk patterns and never treats matching a KB ID as permission
to send arbitrary model-generated text to a customer.
"""
from __future__ import annotations

import re

from .models import AgentProposal, Ticket, TriageResult
from .tools import ToolRegistry

RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Whitelisted FAQ-only replies. Model-written text must NEVER be sent verbatim
# by the auto-response path, even if the model names a real KB article.
SAFE_FAQ_REPLIES = {
    "KB-003": (
        "You can review the available appearance options under Settings > Appearance. "
        "If the setting is missing or not working, please tell us your app and OS versions "
        "so a support specialist can investigate."
    ),
    "KB-004": (
        "Could you share which part of the application you need help with? "
        "We can then direct you to the relevant help documentation."
    ),
}

_BILLING_PATTERNS = (
    r"\b(?:charged|billed|debited|deducted)\s+(?:\w+\s+){0,3}(?:twice|three\s+times|four\s+times|[2-9]\s+times|multiple\s+times)\b",
    r"\b(?:two|three|four|five|six|[2-9])\s+(?:pending\s+)?(?:charges|payments|transactions)\b",
    r"\b(?:duplicate|double|multiple|repeated)\s+(?:charges|transactions|payments|billing)\b",
    r"\b(?:chargeback|disputing\s+(?:all\s+)?(?:charges|payments)|dispute\s+(?:all\s+|the\s+|these\s+)?(?:charges|payments))\b",
    r"\b(?:charged|billed|debited)\s+(?:again|repeatedly)\b",
    r"(?:ถูก)?(?:หักเงิน|ตัดเงิน|เรียกเก็บเงิน|ชาร์จเงิน).{0,28}(?:[2-9]\s*ครั้ง|หลายครั้ง|ซ้ำ)",
    r"(?:[2-9]\s*ครั้ง|หลายครั้ง|ซ้ำ).{0,28}(?:หักเงิน|ตัดเงิน|เรียกเก็บเงิน|ชาร์จเงิน)",
)
_OUTAGE_PATTERNS = (
    r"\b(?:http\s*500|error\s*500|server\s*error\s*500)\b",
    r"\b(?:production|system|service|platform|site|app)\s+(?:is\s+)?(?:completely\s+|totally\s+)?(?:down|unavailable|inaccessible|offline)\b",
    r"\b(?:can\s*not|cannot|can't|unable\s+to)\s+(?:log\s*in|access|sign\s*in)\b",
    r"(?:ระบบ|แอป|เว็บไซต์)(?:ล่ม|ใช้งานไม่ได้|เข้าไม่ได้)",
    r"(?:เข้า(?:ระบบ)?ไม่ได้|ใช้งานไม่ได้|ไม่สามารถเข้า(?:ระบบ|ใช้งาน)ได้)",
)
_MULTI_USER = re.compile(
    r"\b(?:coworkers|colleagues|multiple\s+(?:users|employees|people)|everyone|"
    r"entire\s+(?:company|organization|team)|whole\s+(?:company|organization)|"
    r"all\s+(?:our\s+)?(?:users|employees|staff|teams)|company-wide)\b"
    r"|(?:เพื่อนร่วมงาน|หลายคน|หลายเครื่อง|ทั้งองค์กร|ทั้งบริษัท|ทุกคน|ทั้งทีม)",
    re.IGNORECASE,
)
_DARK_DEFECT = re.compile(r"still\s+(?:shows?\s+)?light|not\s+working|doesn't\s+work|bug|ไม่ทำงาน", re.IGNORECASE)
_NEGATION = re.compile(
    r"(?:\b(?:no|not|never|without|did\s+not|didn't|is\s+not|isn't|was\s+not|wasn't|"
    r"have\s+not|haven't|aren't|there\s+is\s+no)\b|(?:ไม่ได้|ไม่พบ|ไม่มี|ไม่ใช่))"
    r"(?:[\w\s'-]{0,24})$",
    re.IGNORECASE,
)


def _affirmed_pattern(message: str, pattern: str) -> bool:
    """Match a clear signal unless directly negated in the same clause.

    This is intentionally modest: ambiguous wording should be handled by the
    model and routed to humans, not promoted to a claim of certainty.
    """
    for found in re.finditer(pattern, message, re.IGNORECASE):
        prefix = message[max(0, found.start() - 65): found.start()]
        prefix = re.split(r"[.!?;\n,]", prefix)[-1]
        if not _NEGATION.search(prefix):
            return True
    return False


def _floor_urgency(value: str, minimum: str) -> str:
    return value if RANK[value] >= RANK[minimum] else minimum


def _signals(ticket: Ticket) -> tuple[bool, bool, bool]:
    messages = [m.text.lower() for m in ticket.messages]
    billing = any(_affirmed_pattern(m, p) for m in messages for p in _BILLING_PATTERNS)
    outage_symptom = any(_affirmed_pattern(m, p) for m in messages for p in _OUTAGE_PATTERNS)
    multiple_affected = any(_MULTI_USER.search(m) for m in messages)
    # Multi-user confirmed symptom is the trigger; a green status page is not a veto.
    outage = outage_symptom and multiple_affected
    third_party = re.compile(r"\b(?:my coworker|my colleague|my friend|someone else|another customer)\b")
    dark_bug = any("dark mode" in m and _DARK_DEFECT.search(m)
                   and not third_party.search(m) for m in messages)
    return outage, billing, dark_bug


def finalize(ticket: Ticket, proposal: AgentProposal, tools: ToolRegistry, mode: str) -> TriageResult:
    data = proposal.model_dump()
    changes: list[str] = []
    valid = tools.valid_article_ids()
    grounded = list(dict.fromkeys(k for k in data["kb_article_ids"] if k in valid))
    if grounded != data["kb_article_ids"]:
        changes.append("unverified_kb_article_ids_removed")
        data["kb_article_ids"] = grounded

    outage, billing, dark_bug = _signals(ticket)
    if outage:
        if data["urgency"] != "critical":
            changes.append("multi_user_outage_min_critical")
        data["urgency"] = "critical"
        if data["action"] != "escalate_to_human":
            changes.append("outage_requires_human_escalation")
        data["action"] = "escalate_to_human"
        data["assigned_team"] = "Infrastructure / On-call"
        data["draft_response"] = (
            "We understand that several users cannot access the system. "
            "We are escalating your report to our incident team for urgent investigation. "
            "The cause, status of region Asia and recovery time are not yet confirmed."
        )
        data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"],
            "Regional incident not confirmed", "Exact affected user count not verified"]))
    elif billing:
        old = data["urgency"]
        data["urgency"] = _floor_urgency(old, "high")
        if old != data["urgency"]:
            changes.append("repeated_billing_min_high")
        if data["action"] != "escalate_to_human":
            changes.append("billing_dispute_requires_human_escalation")
        data["action"] = "escalate_to_human"
        data["assigned_team"] = "Billing Support"
        data["draft_response"] = (
            "I'm sorry about the repeated charges you reported. We are escalating "
            "this to Billing Support for review. We cannot yet confirm whether the "
            "bank entries were captured or refunded."
        )
        data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"],
            "Bank charges and refunds not verified"]))
    elif dark_bug:
        old = data["urgency"]
        data["urgency"] = _floor_urgency(old, "medium")
        if data["urgency"] != old:
            changes.append("reported_feature_defect_min_medium")
        if data["action"] == "auto_respond":
            changes.append("unverified_defect_requires_specialist")
            data["action"] = "route_to_specialist"
        if data["action"] == "route_to_specialist":
            data["assigned_team"] = "Product Support"
        data["draft_response"] = (
            "Thanks for reporting the appearance issue. Our Product Support team can "
            "investigate why System Default does not work as expected. We cannot "
            "confirm scheduled dark mode is available; its availability isn't confirmed."
        )
        data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"],
            "Scheduled dark-mode support is unverified"]))

    # CRITICAL is always a human escalation, including when the model proposes
    # route_to_specialist rather than auto_respond.
    if data["urgency"] == "critical" and data["action"] != "escalate_to_human":
        if data["action"] == "auto_respond":
            changes.append("auto_response_only_allowed_for_low_urgency")
        changes.append("critical_always_human_escalation")
        data["action"] = "escalate_to_human"
        data["assigned_team"] = "Support Escalation"
        data["draft_response"] = (
            "Your issue has been flagged as critical. We are escalating it to our "
            "support team for immediate investigation; the cause is not yet verified."
        )

    if data["action"] == "auto_respond" and data["urgency"] != "low":
        changes.append("auto_response_only_allowed_for_low_urgency")
        if data["urgency"] == "high":
            data["action"] = "escalate_to_human"
            data["assigned_team"] = "Support Escalation"
        else:
            data["action"] = "route_to_specialist"
            data["assigned_team"] = "General Support"
        data["draft_response"] = (
            "Thank you for reporting this. A specialist will review your issue; "
            "we cannot yet confirm a resolution."
        )

    if data["action"] == "auto_respond":
        safe_article = next((k for k in data["kb_article_ids"] if k in SAFE_FAQ_REPLIES), None)
        if safe_article is None:
            changes.append("no_approved_faq_prevents_auto_response")
            data["action"] = "route_to_specialist"
            data["assigned_team"] = "General Support"
            data["draft_response"] = (
                "Thanks for contacting support. We're routing your question for "
                "review because there is no approved automatic answer."
            )
        else:
            # Do not trust model draft or the retrieved excerpt as instructions.
            data["draft_response"] = SAFE_FAQ_REPLIES[safe_article]
            changes.append("auto_response_replaced_with_approved_faq_template")

    if data["action"] == "auto_respond" and any(not event.ok for event in tools.trace):
        changes.append("tool_failure_prevents_auto_response")
        data["action"] = "route_to_specialist"
        data["assigned_team"] = "General Support"
        data["draft_response"] = (
            "We're checking this with our support team because a required "
            "verification wasn't available."
        )

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
