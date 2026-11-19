import json

import pytest

from evaluation.paired import load_pairs, ticket_for
from triage_agent import tools
from triage_agent.cli import main


PAIRS = {pair["id"]: pair for pair in load_pairs()}


@pytest.mark.parametrize("case_id", ["P01A", "P01B", "P02A", "P02B", "P03A", "P03B", "P08A", "P08B"])
def test_paired_regression_through_cli(case_id, mock_openai, tmp_path, capsys):
    pair = PAIRS[case_id[:-1]]
    side = case_id[-1]
    ticket = ticket_for(pair, side)
    path = tmp_path / "ticket.json"
    path.write_text(ticket.model_dump_json(), encoding="utf-8")

    draft = pair.get("draft", {}).get(side, "Thank you for the update.")
    if case_id in {"P02B", "P03A"}:
        draft = "Thanks for letting us know that everyone can access the app again."
    mock_openai.queue(
        ticket, query="HTTP 500 access", draft_response=draft,
        action="route_to_specialist", assigned_team="Technical Support",
    )
    assert main(["--ticket-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)[0]

    if case_id == "P01A":
        assert result["urgency"] != "critical"
        assert result["action"] != "escalate_to_human"
        assert result["draft_response"] == draft
    elif case_id in {"P01B", "P02A", "P03B"}:
        assert (result["urgency"], result["action"], result["assigned_team"]) == (
            "critical", "escalate_to_human", "Infrastructure / On-call",
        )
        assert "cannot access" in result["draft_response"]
    elif case_id in {"P02B", "P03A"}:
        assert "can access" in result["draft_response"]
        assert "cannot access" not in result["draft_response"]
    else:
        assert (result["action"], result["assigned_team"]) == ("route_to_specialist", "Technical Support")
        if case_id == "P08A":
            assert "Please send us your password" not in result["draft_response"]
            assert "do not share your password" in result["draft_response"]
            assert "password_request_replaced_with_safe_draft" in result["policy_overrides"]
        else:
            assert result["draft_response"] == draft


@pytest.mark.parametrize("side", ["A", "B"], ids=["P12A", "P12B"])
def test_public_status_does_not_confirm_or_disprove_tenant_outage(
    side, mock_openai, monkeypatch, tmp_path, capsys,
):
    pair = PAIRS["P12"]
    ticket = ticket_for(pair, side)
    path = tmp_path / "ticket.json"
    path.write_text(ticket.model_dump_json(), encoding="utf-8")
    load_data = tools.load_data

    def load_with_public_status(filename):
        data = load_data(filename)
        if filename == "system_status.json":
            data["Asia"]["public_status"] = pair["public_status"][side]
        return data

    monkeypatch.setattr(tools, "load_data", load_with_public_status)
    mock_openai.queue(
        ticket, optional_calls=[("check_system_status", {"region": "Asia"})],
    )
    assert main(["--ticket-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)[0]
    assert (result["urgency"], result["action"], result["assigned_team"]) == (
        "critical", "escalate_to_human", "Infrastructure / On-call",
    )
    assert "Regional incident not confirmed" in result["uncertainties"]
    status = result["tool_trace"][-1]["result"]["status"]
    assert status["public_status"] == pair["public_status"][side]
    assert status["incident_confirmed"] is None
