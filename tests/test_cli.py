import json
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
