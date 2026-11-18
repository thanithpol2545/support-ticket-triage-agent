import json
import os
import subprocess
import sys

from triage_agent.agent import AgentExecutionError, DemoTriageAgent
from triage_agent.cli import main


def test_cli_all_demo_and_four_required_fields(capsys):
    assert main(["--mode", "demo", "--all", "--no-trace"]) == 0
    results = json.loads(capsys.readouterr().out)
    assert len(results) == 3
    for r in results:
        assert r["urgency"] in {"critical", "high", "medium", "low"}
        assert r["action"] in {"auto_respond", "route_to_specialist", "escalate_to_human"}
        assert r["product"] and r["issue_types"] and r["sentiment"]
        assert len(r["tools_used"]) >= 2
        assert r["mode"] == "demo_rules"


def test_cli_output_file(tmp_path, capsys):
    path = tmp_path / "result.json"
    assert main(["--ticket", "TICKET-002", "--output", str(path)]) == 0
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["urgency"] == "critical"


def test_cli_rejects_unknown_ticket(capsys):
    assert main(["--ticket", "TICKET-404"]) == 2
    assert "Unknown ticket ID" in capsys.readouterr().err


def test_subprocess_full_trace_json_round_trips_in_legacy_windows_encoding(tmp_path):
    output = tmp_path / 'output.json'
    completed = subprocess.run(
        [sys.executable, '-m', 'triage_agent', '--all', '--output', str(output)],
        env=dict(os.environ, PYTHONIOENCODING='cp874'), capture_output=True, check=True, timeout=30,
    )
    data = json.loads(completed.stdout.decode('cp874'))
    assert data == json.loads(output.read_text(encoding='utf-8'))
    assert '😊' in data[2]['tool_trace'][1]['arguments']['query']


def test_cli_schema_error_never_echoes_ticket_contents(tmp_path, capsys):
    source = tmp_path / 'invalid.json'
    source.write_text(json.dumps({'PRIVATE_TEST_MARKER': 'PRIVATE_VALUE_MARKER'}), encoding='utf-8')
    assert main(['--ticket-file', str(source), '--no-trace']) == 2
    captured = capsys.readouterr()
    assert 'schema validation' in captured.err
    assert 'PRIVATE_' not in captured.err
    assert captured.out == ''


def test_provider_failure_mid_batch_leaves_existing_output_intact(monkeypatch, tmp_path, capsys):
    class InterruptedAgent:
        def run(self, ticket):
            if ticket.ticket_id == 'TICKET-002':
                raise AgentExecutionError('Simulated provider timeout')
            return DemoTriageAgent().run(ticket)

    monkeypatch.setattr('triage_agent.cli.GPTTriageAgent', InterruptedAgent)
    existing = tmp_path / 'result.json'
    existing.write_text('previous output', encoding='utf-8')
    assert main(['--mode', 'live', '--all', '--output', str(existing)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'Simulated provider timeout' in captured.err
    assert existing.read_text(encoding='utf-8') == 'previous output'
