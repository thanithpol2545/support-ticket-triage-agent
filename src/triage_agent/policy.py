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
_REFUND_DISPUTE = r"\b(?:refund dispute|disput(?:e|ing)\s+(?:(?:a|the|my|this)\s+)?refund)\b"
_REFUND_DENIED = (
    r"\b(?:denied|refused|rejected)\s+(?:(?:a|the|my|this)\s+)?refund\b"
    r"|\brefund\s+(?:was\s+)?(?:denied|refused|rejected)\b"
)
_DISPUTES_DECISION = r"\b(?:dispute|appeal)\s+(?:(?:that|the|this)\s+)?(?:decision|denial|rejection)\b"
_HTTP_500 = r"\b(?:http\s*500|error\s*500|server\s*error\s*500)\b"
_OUTAGE_PATTERNS = (
    _HTTP_500,
    r"\b(?:production|system|service|platform|site|app)\s+(?:is\s+)?(?:completely\s+|totally\s+)?(?:down|unavailable|inaccessible|offline)\b",
    r"\b(?:can\s*not|cannot|can't|unable\s+to)\s+(?:log\s*in|access|sign\s*in)\b",
    r"(?:ระบบ|แอป|เว็บไซต์)(?:ล่ม|ใช้งานไม่ได้|เข้าไม่ได้)",
    r"(?:เข้า(?:ระบบ|ใช้งาน)?ไม่ได้|ใช้งานไม่ได้|ไม่สามารถ(?:เข้า(?:ระบบ|ใช้งาน)?|ใช้งาน)ได้)",
)
_MULTI_USER = (
    r"(?:\b(?:coworkers|colleagues|multiple\s+(?:users|employees|people)|everyone|"
    r"entire\s+(?:company|organization|team)|whole\s+(?:company|organization)|"
    r"all\s+(?:our\s+)?(?:users|employees|staff|teams)(?:\s+and\s+(?:users|employees|staff|contractors))?|company-wide)\b"
    r"|เพื่อนร่วมงาน|หลายคน|ทั้งองค์กร|ทั้งบริษัท|ทุกคน|ทั้งทีม)"
)
_OUTAGE_SYMPTOM = "(?:" + "|".join(_OUTAGE_PATTERNS) + ")"
_LOCATION_WORD = r"(?!(?:no|none|not|never|without|can|cannot|is|are|was|were|has|have|and|or)\b)\w+"
_SCOPE_LOCATION = rf"(?:\s+(?:in|at)\s+(?:{_LOCATION_WORD}[ -]){{0,3}}{_LOCATION_WORD})?"
_GROUP_REPORT_WORDS = (
    _SCOPE_LOCATION + r"\s*(?:(?:also|still|now|are|is|keep|keeps|get|gets|getting|got|see|sees|seeing|"
    r"reported|report|reports|has|have|having|the|same|hit|affected|by|with|"
    r"experienc(?:e|es|ing))\s+){0,6}(?:\s|ก็|ยัง|คง|ต่าง){0,12}"
)
# Bind the affected group to the symptom. A group mentioned as unaffected in a
# neighboring clause or message does not establish broader impact.
_SCOPED_OUTAGE_PATTERNS = (
    _MULTI_USER + _GROUP_REPORT_WORDS + _OUTAGE_SYMPTOM,
    _OUTAGE_SYMPTOM + r"\s+(?:for|affecting|across|reported by)\s+(?:(?:my|our|the)\s+)?" + _MULTI_USER,
    _OUTAGE_SYMPTOM + r"\s+company-wide\b",
    r"\b(?:no one|nobody|none\s+of\s+(?:(?:our|my|the)\s+)?" + _MULTI_USER + r")"
    + _SCOPE_LOCATION + r"\s+(?:can|is able to)\s+(?:log\s*in|sign\s*in|access)\b",
)
_SCOPED_FOLLOWUP = (
    _MULTI_USER + _GROUP_REPORT_WORDS + r"\bsame\s+error\b",
    r"\bsame\s+error\s+for\s+(?:(?:my|our|the)\s+)?" + _MULTI_USER,
)
_AFFECTED_GROUP = _MULTI_USER + _GROUP_REPORT_WORDS + r"\baffected\s*$"
_DARK_DEFECT = re.compile(r"still\s+(?:shows?\s+)?light|not\s+working|doesn't\s+work|bug|ไม่ทำงาน", re.IGNORECASE)
_APPEARANCE_TOPIC = r"\b(?:dark mode|dark theme|light theme|appearance)\b|(?:โหมดมืด|ธีมมืด)"
_CLAUSE_BREAK = re.compile(r"[.!?;\n,]|\b(?:but|however|yet)\b|แต่", re.IGNORECASE)
# In Thai access predicates such as เข้าไม่ได้, the failure is already reported.
# The suffix does not negate a separate symptom that follows it.
_NEGATION = re.compile(
    r"(?:\b(?:no|none|not|never|without|did\s+not|didn't|is\s+not|isn't|was\s+not|wasn't|"
    r"have\s+not|haven't|aren't|there\s+is\s+no)\b|"
    r"(?:(?<!เข้า)(?<!เข้าระบบ)(?<!ใช้งาน)ไม่ได้|ไม่พบ|ไม่มี|ไม่ใช่))"
    r"(?:[\w\sก-๙'-]{0,24})$",
    re.IGNORECASE,
)


def _affirmed_pattern(message: str, pattern: str) -> bool:
    """Match a clear signal unless directly negated in the same clause.

    This is intentionally modest: ambiguous wording should be handled by the
    model and routed to humans, not promoted to a claim of certainty.
    """
    for found in re.finditer(pattern, message, re.IGNORECASE):
        prefix = message[max(0, found.start() - 65): found.start()]
        prefix = _CLAUSE_BREAK.split(prefix)[-1]
        if not _NEGATION.search(prefix):
            return True
    return False


_PAYMENT_FAILURE_PATTERNS = (
    r"\b(?:payment\s+failed|failed\s+payment|upgrade\s+failed|failed\s+to\s+(?:pay|upgrade)|card\s+(?:was\s+)?declined)\b",
    r"(?:ชำระเงิน|จ่ายเงิน|อัปเกรด)(?:ไม่สำเร็จ|ไม่ได้)",
)


def _access_problem(ticket: Ticket) -> bool:
    """Affirmed service-access symptoms, even when only one user is affected."""
    return any(_affirmed_pattern(message.text.lower(), pattern)
               for message in ticket.messages for pattern in _OUTAGE_PATTERNS)


def reports_http_500(ticket: Ticket) -> bool:
    return any(_affirmed_pattern(message.text, _HTTP_500) for message in ticket.messages)


def reports_dark_mode_scheduling(ticket: Ticket) -> bool:
    return any("schedule dark mode" in message.text.lower() for message in ticket.messages)


def reports_refund_dispute(ticket: Ticket) -> bool:
    messages = [message.text for message in ticket.messages]
    return any(_affirmed_pattern(message, _REFUND_DISPUTE) for message in messages) or (
        any(_affirmed_pattern(message, _REFUND_DENIED) for message in messages)
        and any(_affirmed_pattern(message, _DISPUTES_DECISION) for message in messages)
    )


def _payment_failure(ticket: Ticket) -> bool:
    """An initial unsuccessful upgrade deserves specialist review, not a FAQ closure."""
    return any(_affirmed_pattern(message.text.lower(), pattern)
               for message in ticket.messages for pattern in _PAYMENT_FAILURE_PATTERNS)


def _floor_urgency(value: str, minimum: str) -> str:
    return value if RANK[value] >= RANK[minimum] else minimum


def _multi_user_outage(messages: list[str]) -> bool:
    symptom_reported = False
    for message in messages:
        for clause in _CLAUSE_BREAK.split(message):
            if any(_affirmed_pattern(clause, pattern) for pattern in _SCOPED_OUTAGE_PATTERNS):
                return True
            symptom_in_clause = _affirmed_pattern(clause, _OUTAGE_SYMPTOM)
            symptom_reported = symptom_reported or symptom_in_clause
            if symptom_reported and any(_affirmed_pattern(clause, pattern) for pattern in _SCOPED_FOLLOWUP):
                return True
            if symptom_in_clause and _affirmed_pattern(clause, _AFFECTED_GROUP):
                return True
    return False


def risk_signals(ticket: Ticket) -> tuple[bool, bool, bool]:
    messages = [m.text.lower() for m in ticket.messages]
    billing = any(_affirmed_pattern(m, p) for m in messages for p in _BILLING_PATTERNS) or reports_refund_dispute(ticket)
    outage = _multi_user_outage(messages)
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
    if "KB-003" in grounded and not any(_affirmed_pattern(message.text, _APPEARANCE_TOPIC) for message in ticket.messages):
        grounded.remove("KB-003")
        changes.append("irrelevant_appearance_faq_removed")
    data["kb_article_ids"] = grounded

    outage, billing, dark_bug = risk_signals(ticket)
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
            "The cause, regional scope and recovery time are pending confirmation."
        )
        data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"],
            "Regional incident not confirmed", "Exact affected user count not verified"]))
        if billing:
            data["draft_response"] += " Billing Support also needs to review the reported billing issue."
            if "Bank charges and refunds not verified" not in data["uncertainties"]:
                data["uncertainties"].append("Bank charges and refunds not verified")
    elif billing:
        old = data["urgency"]
        data["urgency"] = _floor_urgency(old, "high")
        if old != data["urgency"]:
            changes.append("refund_dispute_min_high" if reports_refund_dispute(ticket) else "repeated_billing_min_high")
        if data["action"] != "escalate_to_human":
            changes.append("billing_dispute_requires_human_escalation")
        data["action"] = "escalate_to_human"
        data["assigned_team"] = "Billing Support"
        data["draft_response"] = (
            "Thank you for reporting this billing issue. We are escalating it to Billing Support "
            "for review. The status of any charges or refunds is pending verification."
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
            "Thanks for reporting the appearance issue. Product Support can investigate "
            "how the app handles your appearance settings."
        )
        if reports_dark_mode_scheduling(ticket):
            data["draft_response"] += " Scheduled dark-mode availability is still unverified."
            data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"],
                "Scheduled dark-mode support is unverified"]))

    # A single-user access failure or first failed upgrade is not necessarily an
    # incident, but it is a defect requiring diagnosis rather than auto-closure.
    if not outage and not billing and not dark_bug and (_access_problem(ticket) or _payment_failure(ticket)):
        category = "access" if _access_problem(ticket) else "payment"
        old = data["urgency"]
        data["urgency"] = _floor_urgency(old, "medium")
        if old != data["urgency"]:
            changes.append(f"reported_{category}_failure_min_medium")
        if data["action"] == "auto_respond":
            changes.append("diagnostic_issue_requires_specialist")
            data["action"] = "route_to_specialist"
        if data["action"] == "route_to_specialist":
            data["assigned_team"] = "Billing Support" if category == "payment" else "Technical Support"
        data["draft_response"] = (
            "Thank you for reporting this issue. A support specialist will review the "
            "failure; its cause and resolution have not been confirmed."
        )

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
        elif any(not event.ok for event in tools.trace):
            changes.append("tool_failure_prevents_auto_response")
            data["action"] = "route_to_specialist"
            data["assigned_team"] = "General Support"
            data["draft_response"] = (
                "We're checking this with our support team because a required "
                "verification wasn't available."
            )
        else:
            # Cite the approved source used for this template.
            data["draft_response"] = SAFE_FAQ_REPLIES[safe_article]
            data["kb_article_ids"] = [safe_article]
            changes.append("auto_response_replaced_with_approved_faq_template")

    if data["action"] != "auto_respond" and not data["assigned_team"]:
        changes.append("assigned_fallback_team")
        data["assigned_team"] = "General Support"

    data["reasons"] = list(dict.fromkeys([*data["reasons"], *changes]))
    return TriageResult(
        ticket_id=ticket.ticket_id,
        **data,
        policy_overrides=changes,
        tools_used=list(dict.fromkeys(event.name for event in tools.trace if event.ok)),
        tool_trace=tools.trace,
        mode=mode,
    )
