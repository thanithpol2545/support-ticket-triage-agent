import json
from pathlib import Path

import pytest

from evaluation.paired import load_pairs, ticket_for
from triage_agent.cli import main


REPLAY = json.loads(Path(__file__).with_name("fixtures").joinpath("live_policy_replay.json").read_text(encoding="utf-8"))
PAIRS = {pair["id"]: pair for pair in load_pairs()}


@pytest.fixture
def replay(tickets, mock_openai, tmp_path, capsys):
    def run(ticket_id):
        ticket = tickets[ticket_id] if ticket_id in tickets else ticket_for(PAIRS[ticket_id[:-1]], ticket_id[-1])
        source = tmp_path / "ticket.json"
        source.write_text(ticket.model_dump_json(), encoding="utf-8")
        case = REPLAY["cases"][ticket_id]
        calls = case["calls"]
        optional = [
            (call["name"], call["arguments"] or {"customer_id": ticket.customer.customer_id})
            for call in calls[2:]
        ]
        mock_openai.queue(ticket, query=calls[1]["arguments"]["query"], optional_calls=optional, **case["proposal"])
        assert main(["--ticket-file", str(source), "--audit"]) == 0
        audit = json.loads(capsys.readouterr().out)[0]
        assert audit["proposal"] == case["proposal"]
        result = audit["result"]
        trace = result["tool_trace"]
        assert all(call["ok"] for call in trace)
        assert [
            {"name": call["name"], "arguments": {key: value for key, value in call["arguments"].items() if key != "customer_id"}}
            for call in trace
        ] == calls
        assert [article["id"] for article in trace[1]["result"]["articles"]] == case["retrieved_kb_ids"]
        return result

    return run


def test_retry_audit_reports_attempts_without_confirming_charges(replay):
    result = replay("P05A")
    assert "attempted to pay 3 times" in result["summary"]
    assert "whether any of those attempts resulted in a charge" in result["draft_response"]
    assert "unverified" in result["summary"].lower()
    assert "Multiple charges reported" not in " ".join(result["reasons"])
    assert "payment_attempts_distinguished_from_charges" in result["policy_overrides"]


def test_statement_audit_preserves_reported_charges_and_billing_route(replay):
    result = replay("P05B")
    assert "statement shows 3 charges" in result["summary"]
    assert "status of any charges or refunds is pending verification" in result["draft_response"]
    assert (result["urgency"], result["action"], result["assigned_team"]) == (
        "high", "escalate_to_human", "Billing Support",
    )
    assert "payment_attempts_distinguished_from_charges" not in result["policy_overrides"]


def test_appearance_defect_audit_routes_to_product(replay):
    result = replay("P07B")
    assert (result["urgency"], result["action"], result["assigned_team"]) == (
        "medium", "route_to_specialist", "Product Support",
    )
    assert "System Default" in result["summary"] and "light mode" in result["summary"]
    assert "investigate" in result["draft_response"]
    assert "auto_response_replaced_with_approved_faq_template" not in result["policy_overrides"]


def test_appearance_how_to_audit_remains_eligible_for_faq(replay):
    result = replay("P07A")
    assert (result["urgency"], result["action"], result["assigned_team"]) == ("low", "auto_respond", None)
    assert result["kb_article_ids"] == ["KB-003"]
    assert "Settings > Appearance" in result["draft_response"]


@pytest.mark.parametrize(
    "ticket_id,routing,kb_id,draft_fragment",
    [
        ("TICKET-001", ("high", "escalate_to_human", "Billing Support"), "KB-001", "pending verification"),
        ("TICKET-002", ("critical", "escalate_to_human", "Infrastructure / On-call"), "KB-002", "scope and recovery time are pending confirmation"),
        ("TICKET-003", ("medium", "route_to_specialist", "Product Support"), "KB-003", "Scheduled dark-mode availability is still unverified"),
    ],
)
def test_original_tickets_keep_live_audit_decisions(ticket_id, routing, kb_id, draft_fragment, replay):
    result = replay(ticket_id)
    assert (result["urgency"], result["action"], result["assigned_team"]) == routing
    assert result["kb_article_ids"] == [kb_id]
    assert draft_fragment in result["draft_response"]
