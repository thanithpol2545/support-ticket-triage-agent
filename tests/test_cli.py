import io
import json
import sys

import pytest

from triage_agent.cli import main


def test_cli_all_runs_the_gpt_agent(tickets, mock_openai, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-override")
    billing, outage, appearance = tickets.values()
    mock_openai.queue(billing, query="duplicate charges upgrade", product="Pro upgrade",
                      issue_types=["failed_upgrade", "repeated_charges"], sentiment="frustrated",
                      kb_article_ids=["KB-001"])
    mock_openai.queue(outage, query="HTTP 500 access", product="Enterprise platform",
                      issue_types=["access_failure", "http_500"], sentiment="concerned",
                      kb_article_ids=["KB-002"])
    mock_openai.queue(appearance, query="dark mode appearance", product="Application appearance",
                      issue_types=["appearance_bug", "feature_request"], kb_article_ids=["KB-003"])

    assert main(["--all", "--no-trace"]) == 0
    results = json.loads(capsys.readouterr().out)
    assert [r["ticket_id"] for r in results] == list(tickets)
    assert [(r["urgency"], r["action"], r["assigned_team"]) for r in results] == [
        ("high", "escalate_to_human", "Billing Support"),
        ("critical", "escalate_to_human", "Infrastructure / On-call"),
        ("medium", "route_to_specialist", "Product Support"),
    ]
    for r, citation in zip(results, ("KB-001", "KB-002", "KB-003"), strict=True):
        assert r["product"] and r["issue_types"] and r["sentiment"]
        assert r["kb_article_ids"] == [citation]
        assert r["tools_used"] == ["get_customer_history", "search_knowledge_base"]
        assert "mode" not in r and "tool_trace" not in r
    assert set(results[1]["issue_types"]) == {"access_failure", "http_500"}
    assert mock_openai.create.call_count == 9
    for request in mock_openai.create.call_args_list:
        assert request.kwargs["model"] == "gpt-test-override"
    assert [json.loads(request.kwargs["input"][0]["content"]) for request in mock_openai.create.call_args_list[::3]] == [
        ticket.model_dump() for ticket in tickets.values()
    ]


def test_cli_ticket_and_output(tickets, mock_openai, tmp_path, capsys):
    mock_openai.queue(tickets["TICKET-002"])
    path = tmp_path / "reports" / "result.json"
    assert main(["--ticket", "TICKET-002", "--output", str(path), "--no-trace"]) == 0
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result == json.loads(capsys.readouterr().out)
    assert result["ticket_id"] == "TICKET-002"
    assert result["urgency"] == "critical"
    assert "tool_trace" not in result
    assert mock_openai.create.call_args.kwargs["model"] == "gpt-4.1-mini"


def test_cli_defaults_to_first_ticket(tickets, mock_openai, capsys):
    mock_openai.queue(tickets["TICKET-001"])
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["ticket_id"] == "TICKET-001"
    assert mock_openai.create.call_count == 3


def test_cli_audit_records_one_trajectory(tickets, mock_openai, tmp_path, capsys):
    mock_openai.queue(tickets["TICKET-002"], query="HTTP 500 access")
    mock_openai.replies[-1].model = "gpt-test-snapshot"
    output = tmp_path / "audit.json"
    assert main(["--ticket", "TICKET-002", "--audit", "--output", str(output)]) == 0
    audit = json.loads(output.read_text(encoding="utf-8"))
    assert audit == json.loads(capsys.readouterr().out)
    assert audit["configured_model"] == "gpt-4.1-mini"
    assert audit["response_model"] == "gpt-test-snapshot"
    assert audit["proposal"]["urgency"] == "low"
    assert audit["result"]["urgency"] == "critical"
    trace = audit["result"]["tool_trace"]
    assert [event["name"] for event in trace] == ["get_customer_history", "search_knowledge_base"]
    assert trace[1]["arguments"]["query"] == "HTTP 500 access"
    assert mock_openai.create.call_count == 3


def test_cli_ticket_file_batch_preserves_order(tickets, mock_openai, tmp_path, capsys):
    batch = [tickets["TICKET-003"], tickets["TICKET-001"]]
    path = tmp_path / "tickets.json"
    path.write_text(json.dumps([ticket.model_dump() for ticket in batch]), encoding="utf-8")
    for ticket in batch:
        mock_openai.queue(ticket)
    assert main(["--ticket-file", str(path)]) == 0
    results = json.loads(capsys.readouterr().out)
    assert [r["ticket_id"] for r in results] == [ticket.ticket_id for ticket in batch]


def test_cli_rejects_unknown_ticket(capsys):
    assert main(["--ticket", "TICKET-404"]) == 2
    assert "Unknown ticket ID" in capsys.readouterr().err


def test_full_trace_json_round_trips_in_legacy_windows_encoding(tickets, mock_openai, tmp_path, monkeypatch):
    mock_openai.queue(tickets["TICKET-003"], query="appearance 😊")
    output = tmp_path / "output.json"
    raw = io.BytesIO()
    with monkeypatch.context() as redirect, io.TextIOWrapper(raw, encoding="cp874") as stdout:
        redirect.setattr(sys, "stdout", stdout)
        assert main(["--ticket", "TICKET-003", "--output", str(output)]) == 0
        stdout.flush()
        data = json.loads(raw.getvalue().decode("cp874"))
    assert data == json.loads(output.read_text(encoding="utf-8"))
    assert "😊" in data["tool_trace"][1]["arguments"]["query"]


def test_help_has_no_provider_selection(capsys):
    with pytest.raises(SystemExit) as exit_code:
        main(["--help"])
    assert exit_code.value.code == 0
    assert "--mode" not in capsys.readouterr().out


def test_obsolete_mode_is_rejected(capsys):
    with pytest.raises(SystemExit) as exit_code:
        main(["--mode", "live", "--all"])
    assert exit_code.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized arguments: --mode live" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("key", [None, "   "])
def test_missing_key_reports_setup_without_outputs(monkeypatch, tmp_path, capsys, key):
    if key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", key)
    output = tmp_path / "results.json"
    assert main(["--all", "--output", str(output)]) == 2
    captured = capsys.readouterr()
    assert "OPENAI_API_KEY is required" in captured.err
    assert "PowerShell" in captured.err and "Bash" in captured.err
    assert captured.out == ""
    assert not output.exists()


def test_cli_schema_error_never_echoes_ticket_contents(tmp_path, capsys):
    source = tmp_path / 'invalid.json'
    source.write_text(json.dumps({'PRIVATE_TEST_MARKER': 'PRIVATE_VALUE_MARKER'}), encoding='utf-8')
    assert main(['--ticket-file', str(source), '--no-trace']) == 2
    captured = capsys.readouterr()
    assert 'schema validation' in captured.err
    assert 'PRIVATE_' not in captured.err
    assert captured.out == ''


def test_provider_failure_mid_batch_leaves_existing_output_intact(tickets, mock_openai, tmp_path, capsys):
    mock_openai.queue(tickets["TICKET-001"])
    mock_openai.replies.append(TimeoutError("simulated provider timeout"))
    existing = tmp_path / 'result.json'
    existing.write_text('previous output', encoding='utf-8')
    assert main(['--all', '--output', str(existing)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'OpenAI response failed (TimeoutError)' in captured.err
    assert existing.read_text(encoding='utf-8') == 'previous output'
