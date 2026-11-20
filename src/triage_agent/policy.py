"""Deterministic safety rules around an untrusted model proposal.

This is a conservative backstop, not a complete natural-language classifier. It
catches clear high-risk patterns and never treats matching a KB ID as permission
to send arbitrary model-generated text to a customer.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Literal, NamedTuple

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
_DISPUTES_DECISION = (
    r"\b(?:dispute|appeal|challenge)\s+(?:(?:that|the|this)\s+)?(?:decision|denial|rejection)\b"
    r"|\bchallenge\s+(?:that|this)\s*$"
)
_WITHDRAW_APPEAL = (
    r"\b(?:withdraw|drop|close|cancel)\s+(?:(?:the|my|this)\s+)?(?:refund\s+)?(?:appeal|dispute)\b"
)
_HTTP_500 = r"\b(?:http\s*500|error\s*500|server\s*error\s*500)\b"
_ACCESS_VERB = r"(?:log\s*in|sign\s*in|access|(?:open|load|reach)\s+(?:(?:the|our)\s+)?(?:log[- ]?in|sign[- ]?in)\s+page)"
_THAI_ACCESS_VERB = r"(?:เข้า(?:สู่ระบบ|ระบบ|ใช้งาน)?|ล็อ[กค]อิน|ใช้งาน)"
_OUTAGE_PATTERNS = (
    _HTTP_500,
    r"\b(?:production|system|service|platform|site|app)\s+(?:is\s+)?(?:completely\s+|totally\s+)?(?:down|unavailable|inaccessible|offline)\b",
    rf"\b(?:can\s*not|can['’]t|could\s*not|couldn['’]t|unable\s+to)\s+{_ACCESS_VERB}\b",
    r"(?:ระบบ|แอป|เว็บไซต์)(?:ล่ม|ใช้งานไม่ได้|เข้าไม่ได้)",
    rf"(?:{_THAI_ACCESS_VERB}ไม่ได้|ไม่สามารถ{_THAI_ACCESS_VERB}ได้)",
)
_MULTI_USER = (
    r"(?:\b(?:coworkers|colleagues|multiple\s+(?:users|employees|people)|everyone|"
    r"(?:entire|whole)\s+(?:company|organization|team|branch|office)|"
    r"all\s+(?:our\s+)?(?:users|employees|staff|teams)(?:\s+and\s+(?:users|employees|staff|contractors))?|company-wide)\b"
    r"|เพื่อนร่วมงาน|หลายคน|ทั้งองค์กร|ทั้งบริษัท|ทุกคน|ทั้งทีม|ทั้งสาขา|ทั้งสำนักงาน)"
)
_OUTAGE_SYMPTOM = "(?:" + "|".join(_OUTAGE_PATTERNS) + ")"
_LOCATION_WORD = r"(?!(?:no|none|not|never|without|can|cannot|is|are|was|were|has|have|and|or)\b)\w+"
_LOCATION = rf"(?:{_LOCATION_WORD}[ -]){{0,3}}?{_LOCATION_WORD}"
_SCOPE_LOCATION = rf"(?:\s+(?:in|at|across)\s+{_LOCATION})?"
_GROUP_REPORT_WORDS = (
    _SCOPE_LOCATION + r"\s*(?:(?:also|still|now|are|is|were|was|keep|keeps|get|gets|getting|got|see|sees|seeing|saw|"
    r"reported|report|reports|has|have|having|the|same|hit|affected|blocked|by|with|"
    r"experienc(?:e|es|ing))\s+){0,6}(?:\s|ก็|ยัง|คง|ต่าง){0,12}"
)
_THAI_STATUS_CUE = r"(?:ยัง|กลับ|เข้า|ล็อ[กค]อิน|ใช้งาน|ขึ้น|เจอ|พบ)"
# The particle is a delimiter only when it introduces a status predicate.
_THAI_SCOPE_BOUNDARY = rf"(?:กับ|และ|ทั้งสอง|ทุกคน|พนักงาน|{_THAI_STATUS_CUE}|ก็(?=\s*{_THAI_STATUS_CUE}))"
_THAI_SCOPE_NAME = rf"(?:(?!{_THAI_SCOPE_BOUNDARY})[ก-๙]){{1,26}}"
_THAI_GROUP_LABEL = r"(?:ทีม|สาขา|สำนักงาน|ออฟฟิศ)(?:ที่|ใน)?"
_THAI_SITED_GROUP = rf"{_THAI_GROUP_LABEL}\s*{_THAI_SCOPE_NAME}"
_THAI_NAMED_SCOPE = re.compile(
    rf"(?:{_THAI_GROUP_LABEL}|^\s*ที่)\s*({_THAI_SCOPE_NAME})"
    rf"(?=\s*{_THAI_SCOPE_BOUNDARY})"
)
_THAI_GROUP_LOCATION = (
    r"(?:(?:ใน(?:ทีม|สาขา|สำนักงาน|ออฟฟิศ|ภูมิภาค)|ที่)"
    r"(?:(?!แต่|และ|หรือ|ยังไม่ได้|เข้า|ล็อ[กค]อิน|ขึ้น|ใช้งาน|กลับมา)[ก-๙a-z -]){0,30}?)?"
)
_LOCATED_GROUP = rf"{_MULTI_USER}\s+(?:in|at|across)\s+{_LOCATION}"
# Bind the affected group to the symptom. A group mentioned as unaffected in a
# neighboring clause or message does not establish broader impact.
_SCOPED_OUTAGE_PATTERNS = (
    rf"{_LOCATED_GROUP}(?:\s+and\s+{_LOCATED_GROUP})+" + _GROUP_REPORT_WORDS + _OUTAGE_SYMPTOM,
    rf"{_THAI_SITED_GROUP}(?:\s*(?:กับ|และ)\s*{_THAI_SITED_GROUP})+"
    + r"\s*(?:ก็|ยัง|คง|ต่าง)?\s*" + _OUTAGE_SYMPTOM,
    _MULTI_USER + _GROUP_REPORT_WORDS + _OUTAGE_SYMPTOM,
    rf"\b(?:users|employees|staff)\s+(?:in|at|across)\s+{_LOCATION}" + _GROUP_REPORT_WORDS + _OUTAGE_SYMPTOM,
    _MULTI_USER + _THAI_GROUP_LOCATION + r"\s*(?:ก็|ยัง|คง|ต่าง)?\s*(?:ขึ้น\s*)?" + _OUTAGE_SYMPTOM,
    _OUTAGE_SYMPTOM + r"\s+(?:for|affecting|across|reported by)\s+(?:(?:my|our|the)\s+)?" + _MULTI_USER,
    _OUTAGE_SYMPTOM + r"\s+company-wide\b",
    r"\b(?:no one|nobody|none\s+of\s+(?:(?:our|my|the)\s+)?" + _MULTI_USER + r")"
    + _SCOPE_LOCATION + rf"\s+(?:can|is able to)\s+{_ACCESS_VERB}\b",
)
_IMPACT_REPORT = (
    _OUTAGE_SYMPTOM + r"\s+(?:affects|is\s+affecting)\s+(?:(?:my|our|the)\s+)?" + _MULTI_USER
)
_SCOPED_FOLLOWUP = (
    _MULTI_USER + _GROUP_REPORT_WORDS + r"\bsame\s+error\b",
    r"\bsame\s+error\s+for\s+(?:(?:my|our|the)\s+)?" + _MULTI_USER,
)
_AFFECTED_GROUP = _MULTI_USER + _GROUP_REPORT_WORDS + r"\baffected\s*$"
_DARK_DEFECT = re.compile(
    r"(?:(?:still|continues?\s+to)\s+(?:(?:show|render|display|use|stay|remain)s?\s+)?"
    r"|keeps?\s+(?:showing|rendering|displaying|using)\s+|(?:stays?|remains?|stuck)\s+)"
    r"(?:(?:in|on)\s+)?(?:the\s+)?light\b"
    r"|not\s+working|doesn't\s+work|bug|ไม่ทำงาน|(?:ยัง(?:คง)?|กลับมา)\s*(?:แสดง|ใช้|เป็น)?\s*(?:ธีม|โหมด)สว่าง",
    re.IGNORECASE,
)
_APPEARANCE_TOPIC = r"\b(?:dark mode|dark theme|light mode|light theme|appearance)\b|(?:โหมด|ธีม)(?:มืด|สว่าง)"
_DARK_RECOVERY = (
    r"\b(?:dark (?:mode|theme)|appearance)\s+(?:(?:is|now)\s+)?"
    r"(?:works?|working)\s+(?:again|now|normally|correctly|fine|as\s+expected)\b"
    r"|(?:โหมด|ธีม)มืด(?:กลับมา)?\s*(?:ใช้ได้|ใช้งานได้|ทำงาน(?:ตาม)?ปกติ|ปกติ)แล้ว"
)
_AFTER_RESTART = re.compile(
    r"\bafter\s+(?:(?:i|we|a|the)\s+)?(?:restart(?:ed|ing)?|reboot(?:ed|ing)?)\b"
    r"|หลัง(?:จาก)?\s*(?:รีสตาร์ต|รีสตาร์ท|เปิดแอปใหม่)",
    re.IGNORECASE,
)
_THIRD_PARTY_APPEARANCE = re.compile(r"\b(?:my coworker|my colleague|my friend|someone else|another customer)\b", re.IGNORECASE)
_CLAUSE_BREAK = re.compile(r"[.!?;\n,]|\b(?:but|however|yet)\b|แต่", re.IGNORECASE)
_OUTAGE_CLAUSE_BREAK = re.compile(
    rf"(,\s*but\b(?=\s+only\s+if\b)|{_CLAUSE_BREAK.pattern}|[–—]|(?<=\s)-(?=\s))", re.IGNORECASE,
)
_OUTAGE_CONTINUATIONS = {",", ";", "-", "–", "—"}
_CONDITION_MARKER = (
    r"\b(?:if|unless|in\s+case|in\s+the\s+event\s+that|suppose|supposing|assuming|provided\s+that)\b"
    r"|ถ้า|หาก|สมมติว่า"
)
_HYPOTHETICAL = re.compile(rf"\bwhat\s+if\b|{_CONDITION_MARKER}", re.IGNORECASE)
_POSTFIX_CONDITION = re.compile(rf"\s*(?:only\s+)?(?:{_CONDITION_MARKER})", re.IGNORECASE)
_ONLY_IF = re.compile(r"\s*only\s+if\b", re.IGNORECASE)
_INCIDENT_INSTRUCTION = (
    r"(?:alert|ask|assign|call|check|contact|escalate|file|forward|inform|investigate|notify|"
    r"open|page|ping|route|send|tell|triage)\b|"
    r"(?!(?:then|and|but|or|so|if|as|since|because|once|while|yet|now)\b)[a-z]+\s+"
    r"(?:it|this|them|us|me|(?:out|back|over|off)\s+to|(?:up|in)\s+(?:touch\s+)?with)\b"
)
_REQUEST_START = re.compile(
    r"\s*(?:(?:please|what|when|where|who|how)\b|(?:can|could|would|should|do|are)\s+(?:you|we)\b|"
    rf"let\s+(?:me|us)\s+know\b|(?:then\s+)?(?:do\s+not\s+)?(?:{_INCIDENT_INSTRUCTION}))",
    re.IGNORECASE,
)
_COORDINATED_FOLLOWUP = re.compile(
    r"\b(?:and|then)\s+(?:(?:please|(?:can|could|would|should)\s+(?:you|we|i))\b.*"
    r"|(?:[\w'’-]+\s+){0,8}(?:know|wonder|ask|check|tell|confirm|see|advise)(?:\s+(?:me|us))?)\s*$",
    re.IGNORECASE,
)
_OUTAGE_SCOPE_SUBJECT = rf"(?:{_MULTI_USER}|\b(?:users|employees|staff|system|service|app|site)\b)"
_EXPLICIT_SCOPE = re.compile(
    _OUTAGE_SCOPE_SUBJECT
    + rf"\s+(?:in|at|across)\s+({_LOCATION})(?=\s+(?:also|still|now|can|could|can\s*not|can't|are|is|were|was|has|"
    r"have|cannot|unable|get|gets|getting|got|see|sees|seeing|saw|report|reported|reports|"
    r"keep|keeps|experience|experiences|experiencing|back|restored)\b"
    rf"|\s+and\s+(?={_OUTAGE_SCOPE_SUBJECT}))",
    re.IGNORECASE,
)
_SCOPE_PREFIX = (
    r"^\s*(?:in|at|across)\s+(?!(?:case|fact|practice|theory|reality|general|short|summary)\b)"
    rf"({_LOCATION})"
)
_LEADING_SCOPE = re.compile(_SCOPE_PREFIX + rf"\s+(?={_OUTAGE_SCOPE_SUBJECT})", re.IGNORECASE)
_BARE_SCOPE = re.compile(_SCOPE_PREFIX + r"\s*$", re.IGNORECASE)
_SCOPE_HEADING = re.compile(
    r"^\s*(?!(?:status|update|report|alert|incident|outage|notes?|fyi|summary|context|question|example|"
    r"impact|recovery|resolution|affected\s+(?:users|accounts|areas?|regions?)|symptoms?|scope|workaround|"
    r"time|timeline|next\s+steps?|observations?|mitigation|current\s+assessment)\s*:)"
    r"(?![\w -]*\b(?:reports?|notes?|summar(?:y|ies)|assessments?|timelines?|status|updates?|"
    r"impacts?|recovery|resolution|restoration|findings?|evidence|symptoms?|workarounds?)\b[\w -]*:)"
    rf"({_LOCATION})\s*:(?!\d)",
    re.IGNORECASE,
)
_LOCATION_LABEL = re.compile(r"\b(?:office|region|branch|campus|site|zone|data\s*cent(?:er|re)|hub)$", re.IGNORECASE)
_REGION_NAME = (
    r"(?:\b(?:asia(?:[- ]pacific)?|apac|europe|eu|north america|south america|africa|oceania|australia)\b"
    r"|เอเชีย|ยุโรป)"
)
_REGION_NAMES = {
    "apac": "Asia-Pacific", "asia-pacific": "Asia-Pacific", "asia pacific": "Asia-Pacific",
    "eu": "EU", "เอเชีย": "Asia", "ยุโรป": "Europe",
}
_RESTORED_ACCESS_VERB = r"(?:log\s*in|sign\s*in|access(?:\s+\w+){0,5})"
_ACCESS_RESTORED = (
    r"\s+(?:can|could|(?:are|is|were|was)\s+able\s+to)\s+"
    rf"(?:now\s+{_RESTORED_ACCESS_VERB}|{_RESTORED_ACCESS_VERB}\s+(?:(?:normally|successfully)\s+)?(?:again|now))\b"
)
_SITE_RESTORED = r"\s+(?:(?:is|has\s+been)\s+)?(?:back\s+up|back\s+online|restored)\b"
_LOCATION_QUALIFIER = r"(?:office|region|branch|campus|site)"
_THAI_ACCESS_RESTORED = (
    rf"(?:กลับ(?:มา)?{_THAI_ACCESS_VERB}ได้(?:ครบ|ตามเดิม|ตามปกติ)?(?:แล้ว)?"
    rf"|{_THAI_ACCESS_VERB}ได้(?:ครบ|ตามเดิม|ตามปกติ)?แล้ว)"
)
_RECOVERY_PATTERNS = (
    r"\b(?:everyone|all\s+(?:our\s+)?(?:users|employees|staff)|the\s+whole\s+team)\b"
    + _SCOPE_LOCATION + _ACCESS_RESTORED,
    r"\b(?:users|employees|staff)\s+(?:in|at|across)\s+" + _LOCATION + _ACCESS_RESTORED,
    r"(?:\b(?:system|service|app|site)\b" + _SCOPE_LOCATION + r"|" + _REGION_NAME + r")" + _SITE_RESTORED,
    r"(?:ทุกคน|ทั้งทีม|ทั้งองค์กร|ทั้งบริษัท|ทั้งสาขา|ทั้งสำนักงาน|ระบบ|แอป)"
    + rf"(?:\s*ใน(?:เอเชีย|ยุโรป)|{_THAI_GROUP_LOCATION})\s*" + _THAI_ACCESS_RESTORED,
    _THAI_SITED_GROUP + r"\s*(?:ทุกคน\s*)?" + _THAI_ACCESS_RESTORED,
)
_PASSWORD_REFERENCE = re.compile(r"\bpasswords?\b|รหัสผ่าน", re.IGNORECASE)
_PASSWORD_OBJECT = r"(?:(?:your|the|current|existing|account|login)\s+){0,4}passwords?\b"
_PASSWORD_SENTENCE_BREAK = re.compile(r"[.!?;\n]+")
_SAFE_PASSWORD_ADVICE = re.compile(
    r"(?:please\s+)?(?:"
    r"(?:never|do\s+not|don['’]t)\s+(?:ever\s+)?"
    r"(?:send|share|provide|give|tell|disclose|submit|confirm|reveal|ask\s+for)\s+"
    r"(?:(?:with\s+)?(?:us|me|support)(?:\s+with)?\s+)?"
    + _PASSWORD_OBJECT
    + r"(?:\s+you\s+use\s+to\s+(?:sign|log)\s+in)?(?:\s+(?:to|with)\s+(?:anyone|support|us))?"
    r"|(?:you\s+(?:can|may)\s+)?(?:reset|change)\s+" + _PASSWORD_OBJECT
    + r"(?:\s+(?:in|from|through)\s+(?:your\s+(?:account\s+)?settings|the\s+sign-in\s+screen|the\s+app))?"
    r"|(?:อย่า|ห้าม|ไม่ต้อง|ไม่ควร|ไม่จำเป็นต้อง)\s*(?:ส่ง|แชร์|แจ้ง|บอก|เปิดเผย|ระบุ)\s*รหัสผ่าน"
    r"|(?:รีเซ็ต|เปลี่ยน)\s*รหัสผ่าน)",
    re.IGNORECASE,
)
# In Thai access predicates such as เข้าไม่ได้, the failure is already reported.
# The suffix does not negate a separate symptom that follows it.
_NEGATION = re.compile(
    r"(?:\b(?:no|none|not|never|without|did\s+not|didn't|is\s+not|isn't|was\s+not|wasn't|"
    r"have\s+not|haven't|aren't|there\s+is\s+no)\b|"
    r"(?:(?<!เข้า)(?<!เข้าระบบ)(?<!เข้าสู่ระบบ)(?<!ใช้งาน)(?<!ล็อกอิน)(?<!ล็อคอิน)ไม่ได้|ไม่พบ|ไม่เจอ|ไม่มี|ไม่ใช่))"
    r"(?:[\w\sก-๙'-]{0,24})$",
    re.IGNORECASE,
)


# A denied belief does not establish that an outage affects a group.
_IMPACT_REPORT_NEGATION = re.compile(
    rf"{_NEGATION.pattern}|\b(?:don|doesn|didn)['’]t\s+(?:think|believe)\b[\w\s'’-]{{0,24}}$",
    _NEGATION.flags,
)


def _affirmed_match(
    message: str, pattern: str, *, negation: re.Pattern[str] = _NEGATION
) -> re.Match[str] | None:
    """Match a clear signal unless directly negated in the same clause.

    This is intentionally modest: ambiguous wording should be handled by the
    model and routed to humans, not promoted to a claim of certainty.
    """
    for found in re.finditer(pattern, message, re.IGNORECASE):
        prefix = message[max(0, found.start() - 65): found.start()]
        prefix = _CLAUSE_BREAK.split(prefix)[-1]
        if not negation.search(prefix):
            return found
    return None


def _affirmed_pattern(
    message: str, pattern: str, *, negation: re.Pattern[str] = _NEGATION
) -> bool:
    return _affirmed_match(message, pattern, negation=negation) is not None


_FAILED_UPGRADE = (
    r"\b(?:failed\s+to\s+upgrade|upgrade\s+(?:failed|was\s+unsuccessful|"
    r"did(?:n['’]t|\s+not)\s+(?:go\s+through|succeed)))\b"
    r"|อัปเกรด(?:แล้ว)?\s*(?:ไม่สำเร็จ|ไม่ได้|ไม่ผ่าน)"
)
_PAYMENT_FAILURE_PATTERNS = (
    _FAILED_UPGRADE,
    r"\b(?:payment\s+failed|failed\s+payment|failed\s+to\s+pay|card\s+(?:was\s+)?declined)\b",
    r"(?:ชำระเงิน|จ่ายเงิน)(?:ไม่สำเร็จ|ไม่ได้)",
)
_NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9, "สิบ": 10,
}
_REPEATED_COUNT = r"(?:[2-9]|[1-9][0-9]{1,3}|" + "|".join(_NUMBER_WORDS) + ")"
_PAYMENT_ATTEMPTS = (
    r"\b(?:(?:tried|attempted)\s+to\s+pay|retried\s+(?:the\s+)?payment|"
    r"(?:clicked|pressed|tapped|hit)\s+(?:the\s+)?pay(?:ment)?(?:\s+button)?)\s+"
    rf"({_REPEATED_COUNT})\s+times\b|(?:กด|แตะ|ลอง|พยายาม)\s*(?:ยืนยัน)?\s*(?:จ่าย|ชำระ(?:เงิน)?)(?:ไป)?\s*"
    rf"(?:(?:ครั้ง|รอบ)ที่\s*({_REPEATED_COUNT})|({_REPEATED_COUNT})\s*(?:ครั้ง|รอบ))"
)
_STATEMENT_CHARGES = (
    r"\bstatement\s+(?:shows?|lists?|has)\s+"
    rf"({_REPEATED_COUNT})\s+(?:(?:pending|separate)\s+)?charges\b"
    rf"|ใบแจ้งยอด\s*(?:ขึ้น|แสดง|มี)\s*รายการเรียกเก็บ(?:เงิน)?\s*({_REPEATED_COUNT})\s*รายการ"
)
_STATEMENT_ENTRIES = (
    rf"(?:\bstatement\b|ใบแจ้งยอด)\s*(?:แล้ว(?:ครับ|ค่ะ)?)?\s*(?:ขึ้น|แสดง|มี)\s*รายการ"
    rf"(?:ของ[ก-๙a-z ]{{1,24}}?)?\s*{_REPEATED_COUNT}\s*(?:บรรทัด|รายการ)"
)


_PENDING_BANK_ENTRY = (
    r"\b(?:bank|card)\s+(?:app|statement|account)\s+(?:shows?|lists?|displays?|reports?)\s+"
    r"(?:(?:only|just)\s+)?(?:(?:a|an|one|the|\d+)\s+)?"
    r"pending\s+(?:authori[sz]ation|transaction|charge|payment)\b"
    r"|(?:แอปธนาคาร|บัญชีธนาคาร|ใบแจ้งยอด)\s*(?:แสดง|ขึ้น|มี)\s*"
    r"(?:รายการ\s*(?:pending|รอดำเนินการ)|ยอดกันวงเงิน)"
)
_REFUND_APPROVAL_EMAIL = (
    r"\be-?mail\s+(?:that\s+)?(?:says?|said|saying|confirm(?:s|ed|ing)?|stat(?:es|ed|ing))\s+"
    r"(?:that\s+)?(?:(?:my|our|the)\s+)?refund(?:\s+request)?\s+(?:(?:was|is|has\s+been)\s+)?approved\b"
    r"|\brefund\s+approval\s+e-?mail\b"
    r"|อีเมล\s*(?:แจ้ง|ระบุ|ยืนยัน)(?:มา)?(?:ว่า)?\s*(?:อนุมัติ(?:การ)?คืนเงิน|คืนเงิน(?:ได้รับ)?อนุมัติแล้ว)"
)
_REFUND_CREDIT_MISSING = (
    r"\b(?:cannot|can['’]t|do\s+not|don['’]t|haven['’]t|have\s+not)\s+(?:yet\s+)?"
    r"(?:see|received?)\s+(?:(?:the|a|any|my)\s+)?(?:credit|refund|funds|money)\b"
    r"|\b(?:refund|credit)\s+(?:has\s+not|hasn['’]t)\s+(?:appeared|arrived|posted)\b"
    r"|(?:ยังไม่(?:เห็น|ได้รับ)|ไม่พบ)\s*(?:ยอด(?:เงิน)?คืน|เงินคืน|ยอดโอนคืน)"
)
_REFUND_CREDIT_VISIBLE = (
    r"\b(?:see|received)\s+(?:the|my)\s+(?:credit|refund|funds)\b"
    r"|\b(?:refund|credit)\s+(?:(?:has|now)\s+)?(?:appeared|arrived|posted)\b"
    r"|(?:เห็นยอดเงินคืน|ได้รับเงินคืน|เงินคืนเข้า)(?:แล้ว|เรียบร้อย)"
)

_REFUND_POSITION_NEGATION = re.compile(
    rf"{_NEGATION.pattern}|\b(?:don|didn|doesn)['’]t\b[\w\s'’-]{{0,24}}$", re.IGNORECASE,
)
_ERROR_DENIAL = re.compile(
    rf"{_NEGATION.pattern}|\b(?:no one|nobody|none)\b"
    r"(?:(?!\b(?:and|but|while)\b)[\w\s'-]){0,50}"
    r"\b(?:seeing|sees?|getting|gets?|experiencing|experiences?|receiving|receives?|"
    r"encounter(?:ed|s)?|report(?:ed|s)?|has|have|had)\s+(?:(?:an?|any)\s+)?$",
    re.IGNORECASE,
)


def _access_symptom(clause: str) -> bool:
    return any(
        _affirmed_pattern(clause, pattern, negation=_ERROR_DENIAL if pattern == _HTTP_500 else _NEGATION)
        for pattern in _OUTAGE_PATTERNS
    )


def _access_problem(messages: list[str]) -> bool:
    """Affirmed service-access symptoms, even when only one user is affected."""
    return any(_access_symptom(clause) for clause, _ in _reported_clauses(messages))


_INDIVIDUAL_ACCESS_SCOPE = re.compile(
    r"\b(?:only\s+(?:i|me|my\s+(?:account|device|login|session))|"
    r"i(?:\s+am|['’]m)\s+the\s+only\s+(?:one|person|user))\b"
    rf"|\b(?:everyone\s+else|(?:the\s+)?rest\s+of\s+(?:my|our|the)\s+team)\s+can\s+{_ACCESS_VERB}\b",
    re.IGNORECASE,
)
_AWAITING_OTHER_REPORTS = re.compile(
    r"\bi\s+(?:have\s+not|had\s+not|haven['’]t|hadn['’]t|did\s+not|didn['’]t)\s+"
    r"(?:yet\s+)?(?:heard|hear)\s+(?:back\s+)?from\s+"
    r"(?:(?:the\s+)?rest\s+of\s+)?(?:(?:my|our|the)\s+)?(?:team(?:mates)?|coworkers|colleagues|others)\b",
    re.IGNORECASE,
)
_ADDITIONAL_AFFECTED_REPORT = (
    r"\b(?:teammates|coworkers|colleagues|users|employees|staff)\b"
    r"(?:(?!\b(?:not|never)\b)[^.!?;]){0,120}"
    r"\b(?:same|identical)\s+(?:error|issue|problem|symptom|failure)\b"
)


def _individual_access_scope(messages: list[str]) -> bool:
    clauses = [clause for clause, delimiter in _reported_clauses(messages) if delimiter != "?"]
    if any(_affirmed_pattern(clause, _ADDITIONAL_AFFECTED_REPORT) for clause in clauses):
        return False
    if any(_affirmed_pattern(clause, _INDIVIDUAL_ACCESS_SCOPE.pattern, negation=_IMPACT_REPORT_NEGATION)
           for clause in clauses):
        return True
    first_person_failure = any(
        re.match(r"^\s*(?:I|my)\b", clause, re.IGNORECASE) and _access_symptom(clause)
        for clause in clauses
    )
    return first_person_failure and any(_AWAITING_OTHER_REPORTS.search(clause) for clause in clauses)


def reports_dark_mode_scheduling(ticket: Ticket) -> bool:
    return any("schedule dark mode" in message.text.lower() for message in ticket.messages)


def _refund_dispute_status(messages: list[str]) -> tuple[Literal["active", "withdrawn"] | None, bool]:
    status = None
    declined = False
    for clause, delimiter in _reported_clauses(messages):
        if delimiter == "?":
            continue
        declined = declined or _affirmed_pattern(clause, _REFUND_DENIED)
        if (declined or status) and _affirmed_pattern(clause, _WITHDRAW_APPEAL, negation=_REFUND_POSITION_NEGATION):
            status = "withdrawn"
        elif _affirmed_pattern(clause, _REFUND_DISPUTE, negation=_REFUND_POSITION_NEGATION) or (
            declined and _affirmed_pattern(clause, _DISPUTES_DECISION, negation=_REFUND_POSITION_NEGATION)
        ):
            status = "active"
    return status, declined


def _payment_failure(ticket: Ticket) -> bool:
    """An initial unsuccessful upgrade deserves specialist review, not a FAQ closure."""
    return any(_affirmed_pattern(message.text.lower(), pattern)
               for message in ticket.messages for pattern in _PAYMENT_FAILURE_PATTERNS)


def _reported_payment_count(ticket: Ticket, pattern: str) -> int | None:
    for message in reversed(ticket.messages):
        for clause in reversed(_CLAUSE_BREAK.split(message.text)):
            match = _affirmed_match(clause, pattern)
            if match and not _HYPOTHETICAL.search(clause):
                count = next(value for value in match.groups() if value is not None).casefold()
                return int(count) if count.isdecimal() else _NUMBER_WORDS[count]
    return None


def _floor_urgency(value: str, minimum: str) -> str:
    return value if RANK[value] >= RANK[minimum] else minimum


def _reported_clauses(messages: list[str]) -> Iterator[tuple[str, str]]:
    """Yield reports while keeping a conditional consequence with its premise."""
    for message in messages:
        parts = _OUTAGE_CLAUSE_BREAK.split(message)
        clauses, delimiters = parts[::2], [*parts[1::2], ""]
        conditional = False
        leading_scope = ""
        section_scope = ""
        for index, (clause, delimiter) in enumerate(zip(clauses, delimiters)):
            if not conditional:
                heading = _SCOPE_HEADING.match(clause)
                # An established scope survives inline fields until a clearly named location changes it.
                if heading and (
                    not section_scope or (delimiter == "\n" and not clause[heading.end():].strip())
                    or _LOCATION_LABEL.search(heading[1])
                    or re.fullmatch(_REGION_NAME, heading[1], re.IGNORECASE)
                ):
                    section_scope = heading.group().strip()
                elif leading_scope:
                    if delimiter == "\n" and not clause.strip():
                        continue
                    clause = f"{leading_scope} {clause.lstrip()}"
                    leading_scope = ""
                elif delimiter == "," and _BARE_SCOPE.fullmatch(clause):
                    leading_scope = clause
                    continue
                elif section_scope and not _LEADING_SCOPE.match(clause):
                    clause = f"{section_scope} {clause.lstrip()}"
                if index + 1 < len(clauses):
                    next_clause = clauses[index + 1]
                    only_if = _ONLY_IF.match(next_clause)
                    if only_if and (delimiter in _OUTAGE_CONTINUATIONS or delimiter.casefold().endswith("but")):
                        continue
                    if delimiter in _OUTAGE_CONTINUATIONS and _POSTFIX_CONDITION.match(next_clause):
                        # A complete conditional request attaches its premise to the request itself.
                        follows_with_request = (
                            delimiters[index + 1] in _OUTAGE_CONTINUATIONS
                            and _REQUEST_START.match(clauses[index + 2])
                        )
                        if not follows_with_request:
                            continue
                premise = _HYPOTHETICAL.search(clause)
                if premise is None:
                    yield clause, delimiter
                else:
                    conditional = True
                    followup = _COORDINATED_FOLLOWUP.search(clause, 0, premise.start())
                    if followup:
                        yield clause[:followup.start()], "."
            if delimiter not in _OUTAGE_CONTINUATIONS:
                conditional = False


class _OutageEvidence(NamedTuple):
    # None represents a report without a named region.
    unresolved: set[str | None]
    recovered: set[str | None]


def _first_report(clause: str, patterns: tuple[str, ...]) -> re.Match[str] | None:
    return next((match for pattern in patterns if (match := _affirmed_match(clause, pattern))), None)


def _location_key(name: str) -> str:
    name = re.sub(r"^(?:the|our|my)\s+", "", name.casefold())
    return re.sub(rf"\s+{_LOCATION_QUALIFIER}$", "", name)


def _report_regions(clause: str, matched_report: str, known: set[str]) -> set[str]:
    names = (
        _EXPLICIT_SCOPE.findall(matched_report)
        or _THAI_NAMED_SCOPE.findall(matched_report)
        or _LEADING_SCOPE.findall(clause)
        or _SCOPE_HEADING.findall(clause)
        or _EXPLICIT_SCOPE.findall(clause)
        or _THAI_NAMED_SCOPE.findall(clause)
        or re.findall(_REGION_NAME, clause, re.IGNORECASE)
    )
    reported = set()
    for name in names:
        if name in {"เรา", "ของเรา"}:
            continue
        region = _REGION_NAMES.get(name.casefold(), name.title())
        aliases = [previous for previous in known if _location_key(previous) == _location_key(region)]
        reported.add(aliases[0] if region not in known and len(aliases) == 1 else region)
    return reported


def _known_location_subject(clause: str, known: set[str]) -> tuple[str, str] | None:
    matches = []
    for name in known:
        labels = "|".join(re.escape(label) for label in {name, _location_key(name)})
        subject = rf"^\s*(?:(?:the|our|my)\s+)?(?:{labels})(?:\s+{_LOCATION_QUALIFIER})?"
        if re.match(subject + r"\s+", clause, re.IGNORECASE):
            matches.append((name, subject))
    return matches[0] if len(matches) == 1 else None


def _multi_user_outage(messages: list[str]) -> _OutageEvidence | None:
    unresolved: set[str | None] = set()
    recovered: set[str | None] = set()
    symptom_reported = False
    for clause, delimiter in _reported_clauses(messages):
        known = {name for name in unresolved | recovered if name is not None}
        # A bare place name can identify a status update if it resolves to one reported location.
        location = _known_location_subject(clause, known)
        recovery = _first_report(clause, _RECOVERY_PATTERNS)
        named_recovery = location and _affirmed_pattern(
            clause, location[1] + rf"(?:{_SITE_RESTORED}|(?:\s+(?:users|staff|employees)\b)?{_ACCESS_RESTORED})",
        )
        if delimiter != "?" and (recovery or named_recovery):
            regions = {location[0]} if named_recovery else _report_regions(clause, recovery[0], known)
            if (unresolved or recovered) and len(regions) <= 1 and (regions or None in unresolved):
                region = next(iter(regions), None)
                recovered.add(region)
                if region in unresolved:
                    unresolved.remove(region)
                    symptom_reported = False
            continue

        symptom_in_clause = _access_symptom(clause)
        symptom_reported = symptom_reported or symptom_in_clause
        scopes = _first_report(clause, _SCOPED_OUTAGE_PATTERNS)
        if not scopes and delimiter != "?":
            scopes = _affirmed_match(clause, _IMPACT_REPORT, negation=_IMPACT_REPORT_NEGATION)
        if not scopes and symptom_reported:
            scopes = _first_report(clause, _SCOPED_FOLLOWUP)
        if not scopes and symptom_in_clause:
            scopes = _affirmed_match(clause, _AFFECTED_GROUP)
        if scopes:
            regions = _report_regions(clause, scopes[0], known) or {None}
        elif location and _affirmed_pattern(
            clause, location[1] + rf"\s+(?:is\s+)?(?:still\s+)?(?:blocked|down|offline)\s+for\s+{_MULTI_USER}",
        ):
            regions = {location[0]}
        else:
            continue
        unresolved.update(regions)
        recovered.difference_update(regions)
    return _OutageEvidence(unresolved, recovered) if unresolved or recovered else None


def _appearance_status(messages: list[str]) -> Literal["active", "recovered", "recovered_after_restart"] | None:
    status = None
    for message in messages:
        if not re.search(_APPEARANCE_TOPIC, message, re.IGNORECASE) or _THIRD_PARTY_APPEARANCE.search(message):
            continue
        for clause, delimiter in _reported_clauses([message]):
            if _affirmed_pattern(clause, _DARK_DEFECT.pattern):
                status = "active"
            elif status and delimiter != "?" and _affirmed_pattern(clause, _DARK_RECOVERY):
                status = "recovered_after_restart" if _AFTER_RESTART.search(message) else "recovered"
    return status


def _outage_draft(outage: _OutageEvidence) -> str:
    recovered = ", ".join(sorted(region for region in outage.recovered if region is not None))
    unresolved = ", ".join(sorted(region for region in outage.unresolved if region is not None))
    if not outage.unresolved:
        group = f"users in {recovered}" if recovered and None not in outage.recovered else "users"
        return (
            f"Thank you for confirming that {group} can access the system again. "
            "We are sharing the earlier interruption with our incident team for follow-up. "
            "The cause and regional scope are pending confirmation."
        )
    if recovered:
        scope = f"in {unresolved}" if None not in outage.unresolved else "for the affected users"
        return (
            f"You reported that users in {recovered} can access the system again. "
            f"Your latest report for {unresolved or 'the affected users'} says users could not access the system. "
            f"Whether access has been restored {scope} remains unconfirmed. "
            "We are escalating your report to our incident team for urgent investigation."
        )
    scope = f" in {unresolved}" if None not in outage.unresolved else ""
    return (
        f"We understand that several users{scope} cannot access the system. "
        "We are escalating your report to our incident team for urgent investigation. "
        "The cause, regional scope and recovery time are pending confirmation."
    )


def _unsafe_password_reference(draft: str) -> bool:
    """Require every sentence in a password draft to be approved safety advice."""
    if not _PASSWORD_REFERENCE.search(draft):
        return False
    return any(
        sentence.strip() and not _SAFE_PASSWORD_ADVICE.fullmatch(sentence.strip())
        for sentence in _PASSWORD_SENTENCE_BREAK.split(draft)
    )


def _unverified_bank_status_draft(messages: list[str], tools: ToolRegistry) -> str | None:
    if any(event.name == "check_billing_status" and event.ok and event.result.get("bank_side_verified") is True
           for event in tools.trace):
        return None

    clauses = [clause for clause, delimiter in _reported_clauses(messages) if delimiter != "?"]
    if any(_affirmed_pattern(clause, _REFUND_APPROVAL_EMAIL) for clause in clauses):
        for clause in reversed(clauses):
            if _affirmed_pattern(clause, _REFUND_CREDIT_MISSING):
                return (
                    "You reported receiving an email saying your refund was approved and that the credit "
                    "has not appeared in your bank account. We cannot confirm a transfer or a timeline."
                )
            if _affirmed_pattern(clause, _REFUND_CREDIT_VISIBLE, negation=_REFUND_POSITION_NEGATION):
                break

    if any(_affirmed_pattern(clause, _PENDING_BANK_ENTRY) for clause in clauses):
        return (
            "You reported a pending authorization in your bank app or statement. "
            "We have not verified whether the payment was captured. Support can review the payment status."
        )
    return None


def finalize(ticket: Ticket, proposal: AgentProposal, tools: ToolRegistry) -> TriageResult:
    data = proposal.model_dump()
    changes: list[str] = []
    valid = tools.valid_article_ids()
    grounded = list(dict.fromkeys(k for k in data["kb_article_ids"] if k in valid))
    if grounded != data["kb_article_ids"]:
        changes.append("unverified_kb_article_ids_removed")
    if "KB-003" in data["kb_article_ids"] and not any(
        _affirmed_pattern(message.text, _APPEARANCE_TOPIC) for message in ticket.messages
    ):
        if "KB-003" in grounded:
            grounded.remove("KB-003")
            changes.append("irrelevant_appearance_faq_removed")
        # Handoffs can retain model text, so dropping the article alone leaves its advice in the draft.
        if data["action"] != "auto_respond":
            data["draft_response"] = (
                "Thanks for reaching out. Our support team will review your question "
                "and help you find the right guidance."
            )
            changes.append("handoff_draft_replaced_after_appearance_faq_rejection")
    data["kb_article_ids"] = grounded

    messages = [message.text for message in ticket.messages]
    outage = _multi_user_outage(messages)
    appeal, refund_declined = _refund_dispute_status(messages)
    appearance = _appearance_status(messages)
    statement_charges = _reported_payment_count(ticket, _STATEMENT_CHARGES)
    billing = (
        appeal == "active" or statement_charges is not None
        or any(_affirmed_pattern(message, pattern)
               for message in messages for pattern in (*_BILLING_PATTERNS, _STATEMENT_ENTRIES))
    )
    failed_upgrade = any(_affirmed_pattern(message, _FAILED_UPGRADE) for message in messages)
    if outage:
        if data["urgency"] != "critical":
            changes.append("multi_user_outage_min_critical")
        data["urgency"] = "critical"
        if data["action"] != "escalate_to_human":
            changes.append("outage_requires_human_escalation")
        data["action"] = "escalate_to_human"
        data["assigned_team"] = "Infrastructure / On-call"
        # Keep the existing review of a broad outage while Support defines post-recovery routing.
        data["draft_response"] = _outage_draft(outage)
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
            changes.append("refund_dispute_min_high" if appeal == "active" else "repeated_billing_min_high")
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
        if failed_upgrade and statement_charges is not None:
            data["summary"] = (
                f"Customer reports a failed upgrade and says their statement shows {statement_charges} charges. "
                "Whether those charges settled is unverified."
            )
    elif appeal == "withdrawn":
        if data["action"] == "auto_respond":
            data["action"] = "route_to_specialist"
        data["assigned_team"] = "Billing Support"
        data["summary"] = (
            "Customer reports that their refund request was denied and asks to withdraw the appeal. "
            "Completion has not been confirmed." if refund_declined
            else "Customer asked to withdraw their refund appeal. Completion has not been confirmed."
        )
        data["draft_response"] = (
            "Thank you for letting us know that you want to withdraw your appeal. "
            "Billing Support can review that request. We cannot confirm that the appeal "
            "has been closed or that a refund has been issued."
        )
        changes.append("refund_appeal_withdrawal_acknowledged")
    elif appearance:
        if appearance == "active":
            old = data["urgency"]
            data["urgency"] = _floor_urgency(old, "medium")
            if data["urgency"] != old:
                changes.append("reported_feature_defect_min_medium")
            if data["action"] == "auto_respond":
                changes.append("unverified_defect_requires_specialist")
                data["action"] = "route_to_specialist"
            data["draft_response"] = (
                "Thanks for reporting the appearance issue. Product Support can investigate "
                "how the app handles your appearance settings."
            )
        else:
            if data["action"] == "auto_respond":
                data["action"] = "route_to_specialist"
            recovery_context = " after a restart" if appearance == "recovered_after_restart" else ""
            data["summary"] = f"Customer reported an appearance issue and confirmed that the theme is working again{recovery_context}."
            data["draft_response"] = (
                f"Thanks for the update. You reported that your theme is working again{recovery_context}. "
                "Product Support can review the earlier behavior if needed."
            )
            changes.append("reported_appearance_recovery_acknowledged")
        if data["action"] == "route_to_specialist":
            data["assigned_team"] = "Product Support"
        if reports_dark_mode_scheduling(ticket):
            data["draft_response"] += " Scheduled dark-mode availability is still unverified."
            data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"],
                "Scheduled dark-mode support is unverified"]))
    elif _access_problem(messages):
        if RANK[data["urgency"]] < RANK["high"] or _individual_access_scope(messages):
            if (data["urgency"], data["action"], data["assigned_team"]) != ("medium", "route_to_specialist", "Technical Support"):
                changes.append("access_issue_routes_to_technical_support")
            data["urgency"] = "medium"
            data["action"] = "route_to_specialist"
            data["assigned_team"] = "Technical Support"
            data["draft_response"] = (
                "Thank you for reporting this issue. A support specialist will review the "
                "failure; its cause and resolution have not been confirmed."
            )
        else:
            # An inconclusive parser match does not justify downgrading a high-risk proposal.
            if data["action"] == "escalate_to_human" or data["urgency"] == "critical":
                data["action"] = "escalate_to_human"
                data["assigned_team"] = "Infrastructure / On-call"
                followup = "We are escalating this access report to our incident team for investigation."
            else:
                if data["action"] == "auto_respond":
                    data["action"] = "route_to_specialist"
                    data["assigned_team"] = "Technical Support"
                followup = "A support specialist will investigate this access report."
            data["draft_response"] = f"{followup} The number of affected users and regional scope are unconfirmed."
            data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"], "Access impact scope unconfirmed"]))
            changes.append("access_urgency_retained_with_unconfirmed_scope")
    elif _payment_failure(ticket):
        old = data["urgency"]
        data["urgency"] = _floor_urgency(old, "medium")
        if old != data["urgency"]:
            changes.append("reported_payment_failure_min_medium")
        if data["action"] == "auto_respond":
            changes.append("diagnostic_issue_requires_specialist")
            data["action"] = "route_to_specialist"
        if data["action"] == "route_to_specialist":
            data["assigned_team"] = "Billing Support"
        data["draft_response"] = (
            "Thank you for reporting this issue. A support specialist will review the "
            "failure; its cause and resolution have not been confirmed."
        )

        attempts = _reported_payment_count(ticket, _PAYMENT_ATTEMPTS) if failed_upgrade else None
        if attempts is not None:
            data["summary"] = (
                f"Customer reports the upgrade failed and they attempted to pay {attempts} times. "
                "Whether the attempts resulted in charges is unverified."
            )
            data["draft_response"] = (
                "Thank you for reporting the failed upgrade and repeated attempts to pay. "
                "We have not verified whether any of those attempts resulted in a charge. "
                "Our support team will review the payment and upgrade status."
            )
            data["reasons"] = ["Customer reports an upgrade failure and repeated payment attempts"]
            data["uncertainties"] = list(dict.fromkeys([*data["uncertainties"],
                "Whether the payment attempts resulted in charges is unverified"]))
            changes.append("payment_attempts_distinguished_from_charges")

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

    if data["action"] != "auto_respond" and not (outage or appeal or appearance or _access_problem(messages)):
        bank_draft = _unverified_bank_status_draft(messages, tools)
        if bank_draft is not None:
            data["draft_response"] = bank_draft
            changes.append("bank_status_draft_grounded_in_customer_report")

    if _unsafe_password_reference(data["draft_response"]):
        data["draft_response"] = "Thank you for contacting support. For your security, please do not share your password."
        changes.append("password_request_replaced_with_safe_draft")

    data["reasons"] = list(dict.fromkeys([*data["reasons"], *changes]))
    return TriageResult(
        ticket_id=ticket.ticket_id,
        **data,
        policy_overrides=changes,
        tools_used=list(dict.fromkeys(event.name for event in tools.trace if event.ok)),
        tool_trace=tools.trace,
    )
