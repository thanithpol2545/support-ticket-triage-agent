import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from triage_agent.agent import load_tickets


@pytest.fixture
def tickets():
    return {t.ticket_id: t for t in load_tickets()}


class ScriptedResponses:
    """Queue API replies so tests run the actual agent, registry, and policy."""

    def __init__(self):
        self.replies = []
        self.create = Mock(side_effect=iter(self.replies))

    def queue(self, ticket, *, query="general help guide", optional_calls=(), **proposal_fields):
        calls = [
            ("get_customer_history", {"customer_id": ticket.customer.customer_id}),
            ("search_knowledge_base", {"query": query}),
            *optional_calls,
        ]
        for index, (name, arguments) in enumerate(calls):
            call = SimpleNamespace(
                type="function_call", name=name, arguments=json.dumps(arguments),
                call_id=f"{ticket.ticket_id}-{index}",
            )
            self.replies.append(SimpleNamespace(status="completed", output=[call]))

        proposal = {
            "urgency": "low", "product": "Application", "issue_types": ["support_request"],
            "sentiment": "neutral", "action": "auto_respond", "assigned_team": None,
            "summary": "Customer requests help.", "reasons": ["Customer report"],
            "kb_article_ids": [], "draft_response": "Thanks for contacting support.",
            "uncertainties": [],
        } | proposal_fields
        self.replies.append(SimpleNamespace(status="completed", output=[], output_text=json.dumps(proposal)))


@pytest.fixture
def mock_openai(monkeypatch):
    responses = ScriptedResponses()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr("openai.OpenAI", Mock(return_value=SimpleNamespace(responses=responses)))
    return responses
