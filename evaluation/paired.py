"""Prepare paired tickets and reproduce the direct-text retrieval probes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from triage_agent.models import Customer, Message, Ticket
from triage_agent.tools import ToolRegistry

PAIRS = Path(__file__).with_name("paired_cases.json")
EDGES = Path(__file__).with_name("adversarial_cases.json")


def load_pairs() -> list[dict]:
    return json.loads(PAIRS.read_text(encoding="utf-8"))


def load_edges() -> list[dict]:
    return json.loads(EDGES.read_text(encoding="utf-8"))


def edge_ticket(case_id: str, text: str) -> Ticket:
    return Ticket(
        ticket_id=case_id,
        customer=Customer(customer_id=f"test-{case_id}", plan="Enterprise", tenure_months=1),
        messages=[Message(when="now", text=text)],
    )


def ticket_for(pair: dict, side: str) -> Ticket:
    case_id = pair["id"] + side
    return Ticket(
        ticket_id=case_id,
        customer=Customer(customer_id=f"REGRESSION-{case_id}", plan="unknown", tenure_months=0),
        messages=[
            Message(when=str(index), text=text)
            for index, text in enumerate(pair.get("prefix", []) + pair[side], 1)
        ],
    )


def retrieval_probes(pairs: list[dict]) -> list[dict]:
    rows = []
    for pair in pairs:
        if "expected_faq" not in pair:
            continue
        for side, expected in pair["expected_faq"].items():
            ticket = ticket_for(pair, side)
            query = ticket.messages[0].text
            lookup = ToolRegistry(ticket).call("search_knowledge_base", {"query": query})
            top_three = [article["id"] for article in lookup["articles"]]
            rows.append({
                "case_id": ticket.ticket_id,
                "query": query,
                "expected_faq": expected,
                "top_three": top_three,
                "hit_at_3": expected in top_three if expected else None,
            })
    return rows


def model_queries(audit: list[dict]) -> list[dict]:
    return [
        {
            "case_id": entry["result"]["ticket_id"],
            "model": entry["response_model"] or entry["configured_model"],
            "query": event["arguments"].get("query"),
            "top_three": [article["id"] for article in event["result"].get("articles", [])],
            "ok": event["ok"],
        }
        for entry in audit
        for event in entry["result"]["tool_trace"]
        if event["name"] == "search_knowledge_base"
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Create the 20 tickets that vary customer text for live CLI")
    prepare.add_argument("--output", type=Path, required=True)
    edges = commands.add_parser("prepare-edges", help="Create the nine original edge fixtures for live CLI")
    edges.add_argument("--output", type=Path, required=True)
    commands.add_parser("probe", help="Report all six P09–P11 lookups using the literal customer text")
    queries = commands.add_parser("model-queries", help="Extract model-generated KB queries from a CLI audit batch")
    queries.add_argument("audit", type=Path)
    args = parser.parse_args()

    if args.command == "prepare":
        entries = [
            ticket_for(pair, side).model_dump()
            for pair in load_pairs()
            if pair["A"] != pair["B"]
            for side in ("A", "B")
        ]
        args.output.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    elif args.command == "prepare-edges":
        entries = [edge_ticket(case["id"], case["text"]).model_dump() for case in load_edges()]
        args.output.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    elif args.command == "probe":
        print(json.dumps(retrieval_probes(load_pairs()), indent=2))
    else:
        print(json.dumps(model_queries(json.loads(args.audit.read_text(encoding="utf-8"))), indent=2))


if __name__ == "__main__":
    main()
