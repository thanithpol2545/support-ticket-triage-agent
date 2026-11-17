from typing import get_args
import pytest
from pydantic import ValidationError
from triage_agent.agent import load_tickets
from triage_agent.models import Action, AgentProposal, Ticket, Urgency, PROPOSAL_JSON_SCHEMA


def test_exact_urgency_labels_and_actions():
    assert set(get_args(Urgency)) == {"critical", "high", "medium", "low"}
    assert set(get_args(Action)) == {"auto_respond", "route_to_specialist", "escalate_to_human"}


def test_three_original_ticket_threads_preserved():
    tickets = load_tickets()
    assert len(tickets) == 3
    assert all(len(t.messages) == 4 for t in tickets)
    assert "THREE charges of $29.99" in tickets[0].messages[2].text
    assert "error 500" in tickets[1].messages[0].text
    assert "schedule dark mode" in tickets[2].messages[3].text


def test_invalid_urgency_rejected():
    with pytest.raises(ValidationError):
        AgentProposal(urgency="urgent", product="App", issue_types=["bug"], sentiment="neutral",
            action="auto_respond", assigned_team=None, summary="x", reasons=["x"], kb_article_ids=[],
            draft_response="x", uncertainties=[])


def test_malformed_or_empty_ticket_rejected(tickets):
    item = tickets["TICKET-001"].model_dump()
    item["messages"] = []
    with pytest.raises(ValidationError):
        Ticket.model_validate(item)


def test_strict_output_schema_contract():
    assert set(PROPOSAL_JSON_SCHEMA["required"]) == set(PROPOSAL_JSON_SCHEMA["properties"])
    assert PROPOSAL_JSON_SCHEMA["additionalProperties"] is False
