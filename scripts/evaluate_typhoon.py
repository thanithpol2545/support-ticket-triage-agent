"""Manual REAL-provider smoke/evaluation runner; never stores an API key.

Usage after setting TYPHOON_API_KEY in your shell:
    python scripts/evaluate_typhoon.py --limit 3
    python scripts/evaluate_typhoon.py --include-edge --limit 12

Expected labels for synthetic cases are proposals for evaluation, not a gold set.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from time import perf_counter

from triage_agent.agent import AgentExecutionError, load_tickets
from triage_agent.models import Customer, Message, Ticket
from triage_agent.typhoon import TyphoonTriageAgent


def fixtures(include_edge: bool):
    baseline = list(zip(load_tickets(), [
        ("high", "escalate_to_human"),
        ("critical", "escalate_to_human"),
        ("medium", "route_to_specialist"),
    ]))
    if include_edge:
        path = Path(__file__).resolve().parents[1] / "evaluation" / "adversarial_cases.json"
        for edge in json.loads(path.read_text(encoding="utf-8")):
            ticket = Ticket(ticket_id=edge["id"],
                customer=Customer(customer_id=f"eval-{edge['id']}", plan="Enterprise", tenure_months=1),
                messages=[Message(when="now", text=edge["text"])])
            baseline.append((ticket, (edge["expected_urgency"], edge["expected_action"])))
    return baseline


def main():
    parser = argparse.ArgumentParser(description="Real Typhoon triage smoke/evaluation (manual execution only)")
    parser.add_argument("--include-edge", action="store_true", help="Include 9 synthetic adversarial cases")
    parser.add_argument("--limit", type=int, default=3, help="Maximum number of tickets (1..12)")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be >=1")
    try:
        agent = TyphoonTriageAgent()
    except AgentExecutionError as exc:
        print(f"Setup error: {exc}")
        return 2
    records=[]
    for ticket, (expected_urgency, expected_action) in fixtures(args.include_edge)[:args.limit]:
        started = perf_counter()
        try:
            result=agent.run(ticket)
            match_urgency = result.urgency == expected_urgency
            match_action = expected_action is None or result.action == expected_action
            records.append({"ticket_id": ticket.ticket_id, "status": "ok",
                "urgency": result.urgency, "action": result.action,
                "expected_urgency": expected_urgency, "expected_action": expected_action,
                "urgency_match": match_urgency, "action_match": match_action,
                "tools_used": result.tools_used, "policy_overrides": result.policy_overrides})
        except AgentExecutionError as exc:
            records.append({"ticket_id": ticket.ticket_id, "status": "error",
                "error_type": type(exc).__name__, "details": str(exc)})
        records[-1]["latency_ms"] = round((perf_counter() - started) * 1000)
    print(json.dumps({"provider": "typhoon", "real_api_test": True,
        "model": agent.model,
        "important": "Synthetic expected labels are proposals, not human-annotated ground truth",
        "evaluated": len(records), "records": records}, ensure_ascii=False, indent=2))
    return 0 if all(r["status"] == "ok" and r["urgency_match"] and r["action_match"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
