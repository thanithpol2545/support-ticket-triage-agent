"""Read-only mock tools and OpenAI function schemas."""
from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import Ticket, ToolTrace


def load_data(filename: str) -> Any:
    return json.loads(files("triage_agent").joinpath("data", filename).read_text(encoding="utf-8"))


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HistoryArgs(_Arguments):
    customer_id: str = Field(min_length=1, max_length=100)


class KBArgs(_Arguments):
    query: str = Field(min_length=2, max_length=2000)


class BillingArgs(_Arguments):
    customer_id: str = Field(min_length=1, max_length=100)


class StatusArgs(_Arguments):
    region: str = Field(min_length=1, max_length=80)


TOOL_SCHEMAS = [
    {
        "type": "function", "name": "get_customer_history", "description": "Read the customer's mock account context and support history before triage.",
        "strict": True,
        "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"], "additionalProperties": False},
    },
    {
        "type": "function", "name": "search_knowledge_base", "description": "Search local support FAQs and troubleshooting docs; returns grounded article IDs and excerpts.",
        "strict": True,
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
    },
    {
        "type": "function", "name": "check_billing_status", "description": "Read mock billing account facts. Does not issue refunds or claim bank-side settlement.",
        "strict": True,
        "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"], "additionalProperties": False},
    },
    {
        "type": "function", "name": "check_system_status", "description": "Inspect the mock public status and regional diagnostic availability. Not an actual incident monitor.",
        "strict": True,
        "parameters": {"type": "object", "properties": {"region": {"type": "string"}}, "required": ["region"], "additionalProperties": False},
    },
]

ARG_MODELS = {
    "get_customer_history": HistoryArgs,
    "search_knowledge_base": KBArgs,
    "check_billing_status": BillingArgs,
    "check_system_status": StatusArgs,
}


def _match_keyword(text: str, keyword: str) -> bool:
    # Whole-word matching for English, substring matching for unsegmented Thai text.
    if re.search(r"[ก-๙]", keyword):
        return keyword.lower() in text
    return re.search(r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)", text) is not None


class ToolRegistry:
    """Scopes every request to the ticket being processed; no cross-customer reads."""

    def __init__(self, ticket: Ticket):
        self.ticket = ticket
        self.trace: list[ToolTrace] = []
        self.kb = load_data("kb.json")
        self.billing = load_data("billing.json")
        self.status = load_data("system_status.json")

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name not in ARG_MODELS:
                raise ValueError("Unknown tool")
            args = ARG_MODELS[name].model_validate(arguments)
            if name in {"get_customer_history", "check_billing_status"}:
                if args.customer_id != self.ticket.customer.customer_id:
                    raise ValueError("Customer ID does not belong to this ticket")
            if name == "get_customer_history":
                result = {"customer": self.ticket.customer.model_dump(), "history": self.ticket.customer.notes,
                          "source": "mock_customer_profile"}
            elif name == "search_knowledge_base":
                query = args.query.lower()
                scored = []
                for article in self.kb:
                    score = sum(1 for kw in article["keywords"] if _match_keyword(query, kw))
                    if score:
                        scored.append((score, article["id"], article))
                scored.sort(key=lambda x: (-x[0], x[1]))
                result = {"articles": [{"id": a["id"], "title": a["title"], "excerpt": a["content"]}
                                       for _, _, a in scored[:3]], "source": "mock_kb"}
            elif name == "check_billing_status":
                result = {"customer_id": args.customer_id, "record": self.billing.get(args.customer_id),
                          "source": "mock_billing", "bank_side_verified": False}
            else:
                region = args.region
                if region.lower() in {"thailand", "asia-pacific", "apac"}:
                    region = "Asia"
                if region not in self.status:
                    result = {"region": region, "status": None, "source": "mock_status",
                              "message": "No diagnostic record for this region"}
                else:
                    result = {"region": region, "status": self.status[region], "source": "mock_status"}
            ok = True
        except (ValidationError, ValueError, TypeError, KeyError, IndexError) as exc:
            result = {"error": "Invalid tool input or mock data" if isinstance(exc, (KeyError, IndexError)) else str(exc), "source": "tool_error"}
            ok = False
        self.trace.append(ToolTrace(name=name, arguments=arguments, result=result, ok=ok))
        return result

    def valid_article_ids(self) -> set[str]:
        ids: set[str] = set()
        for event in self.trace:
            if event.name == "search_knowledge_base" and event.ok:
                ids.update(a["id"] for a in event.result.get("articles", []))
        return ids
