"""Strict input/output contracts; urgency and actions mirror the original assignment."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Urgency = Literal["critical", "high", "medium", "low"]
Action = Literal["auto_respond", "route_to_specialist", "escalate_to_human"]
Sentiment = Literal["positive", "neutral", "concerned", "frustrated", "angry"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Message(StrictModel):
    when: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Customer(StrictModel):
    customer_id: str = Field(min_length=1)
    plan: str = Field(min_length=1)
    region: str | None = None
    tenure_months: int = Field(ge=0)
    seats: int | None = Field(default=None, ge=1)
    notes: str = ""


class Ticket(StrictModel):
    ticket_id: str = Field(min_length=1)
    customer: Customer
    messages: list[Message] = Field(min_length=1)


class AgentProposal(StrictModel):
    urgency: Urgency
    product: str = Field(min_length=1)
    issue_types: list[str] = Field(min_length=1)
    sentiment: Sentiment
    action: Action
    assigned_team: str | None
    summary: str = Field(min_length=1)
    reasons: list[str] = Field(min_length=1)
    kb_article_ids: list[str]
    draft_response: str = Field(min_length=1)
    uncertainties: list[str]


class ToolTrace(StrictModel):
    name: str
    arguments: dict
    result: dict
    ok: bool


class TriageResult(StrictModel):
    ticket_id: str
    urgency: Urgency
    product: str
    issue_types: list[str]
    sentiment: Sentiment
    action: Action
    assigned_team: str | None
    summary: str
    reasons: list[str]
    kb_article_ids: list[str]
    draft_response: str
    uncertainties: list[str]
    policy_overrides: list[str]
    tools_used: list[str]
    tool_trace: list[ToolTrace]

    @model_validator(mode="after")
    def check_handoff(self) -> "TriageResult":
        if self.action != "auto_respond" and not self.assigned_team:
            raise ValueError("Human routing requires assigned_team")
        return self


# Strict JSON Schema for Responses API (every field is required).
# Keep in sync with AgentProposal; validated locally with Pydantic on every result.
PROPOSAL_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "urgency": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "product": {"type": "string"},
        "issue_types": {"type": "array", "items": {"type": "string"}},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "concerned", "frustrated", "angry"]},
        "action": {"type": "string", "enum": ["auto_respond", "route_to_specialist", "escalate_to_human"]},
        "assigned_team": {"type": ["string", "null"]},
        "summary": {"type": "string"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "kb_article_ids": {"type": "array", "items": {"type": "string"}},
        "draft_response": {"type": "string"},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["urgency", "product", "issue_types", "sentiment", "action", "assigned_team", "summary", "reasons", "kb_article_ids", "draft_response", "uncertainties"],
    "additionalProperties": False,
}
