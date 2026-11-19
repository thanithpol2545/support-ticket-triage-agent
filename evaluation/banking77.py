"""Reproduce and score the BANKING77 pilot without calling a model."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import unicodedata
from pathlib import Path
from urllib.request import urlopen

from triage_agent.models import Customer, Message, Ticket

REVISION = "57ec275d8078af65b7731c2a98be812d844a6d6b"
SOURCE = f"https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/{REVISION}/banking_data/test.csv"
CSV_SHA256 = "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d"
SNAPSHOT = Path(__file__).with_name("banking77-pilot-tickets.json")
RUBRIC = "banking77-issue-types-v1"

# Locked before any GPT output. Every alias matches a whole normalized issue_type.
INTENTS = {
    "card_payment_fee_charged": (
        (814, 817, 833, 835),
        ("card payment fee", "card fee", "card payment fees", "card transaction fee",
         "card payment fee inquiry", "card payment fee question", "card fee inquiry",
         "fee for paying by card", "card usage fee", "fee charged for card payment"),
    ),
    "card_payment_not_recognised": (
        (1094, 1107, 1110, 1120),
        ("card payment not recognized", "unrecognized card payment", "unrecognised card payment",
         "unrecognized payment", "unrecognised payment", "unrecognized transaction",
         "unrecognised transaction", "unknown card payment", "unknown transaction",
         "unrecognized charge", "unrecognised charge"),
    ),
    "declined_card_payment": (
        (1811, 1815, 1828, 1834),
        ("card payment declined", "card transaction declined", "declined card transaction",
         "card transaction rejected", "card payment rejected", "rejected card payment",
         "card declined", "card decline", "payment declined", "declined payment"),
    ),
    "pending_card_payment": (
        (1604, 1612, 1627, 1630),
        ("card payment pending", "pending payment", "payment pending", "pending card transaction",
         "pending transaction", "pending charge", "pending card charge", "pending payment status",
         "pending card payment inquiry", "pending payment inquiry", "card transaction pending"),
    ),
}
PENDING = {
    "B77-TEST-1604": "The text asks how to finalize a payment without stating it is pending.",
    "B77-TEST-1815": "The text says card payment does not work without stating it was declined.",
}


def sample_id(number: int) -> str:
    return f"B77-TEST-{number:04d}"


EXPECTED = {sample_id(number): intent for intent, (numbers, _) in INTENTS.items() for number in numbers}


def generate(source: bytes) -> list[Ticket]:
    if hashlib.sha256(source).hexdigest() != CSV_SHA256:
        raise ValueError("Source CSV SHA-256 does not match the pinned test split.")
    rows = list(enumerate(csv.DictReader(io.StringIO(source.decode("utf-8"), newline="")), 1))
    selected = []
    for intent, (numbers, _) in INTENTS.items():
        candidates = [(number, row) for number, row in rows if row["category"] == intent]
        first_four = sorted(
            candidates,
            key=lambda item: (hashlib.sha256(f"ooca-external-pilot-v1:{item[0]}".encode("ascii")).digest(), item[0]),
        )[:4]
        if sorted(number for number, _ in first_four) != list(numbers):
            raise ValueError(f"Selected rows differ from the rubric for {intent}.")
        selected.extend(first_four)
    return [
        Ticket(
            ticket_id=sample_id(number),
            customer=Customer(customer_id=f"EXT-{sample_id(number)}", plan="unknown", tenure_months=0),
            messages=[Message(when="unknown", text=row["text"])],
        )
        for number, row in sorted(selected)
    ]


def snapshot_tickets() -> list[Ticket]:
    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    tickets = [Ticket.model_validate(row) for row in raw]
    if [ticket.ticket_id for ticket in tickets] != sorted(EXPECTED):
        raise ValueError("Pilot Ticket IDs or order differ from the rubric.")
    return tickets


def normalize(label: str) -> str:
    label = unicodedata.normalize("NFKC", label).casefold()
    return re.sub(r"[\W_]+", " ", label).strip()


def score(rows: list[dict]) -> dict:
    if not isinstance(rows, list):
        raise ValueError("Expected a CLI result array from --ticket-file.")
    predictions = {}
    for row in rows:
        result = row.get("result", row) if isinstance(row, dict) else None
        if not isinstance(result, dict):
            raise ValueError("Each entry must contain a CLI result.")
        ticket_id = result.get("ticket_id")
        if not isinstance(ticket_id, str) or ticket_id not in EXPECTED or ticket_id in PENDING:
            raise ValueError(f"Unexpected or pending ticket ID: {ticket_id!r}")
        if ticket_id in predictions:
            raise ValueError(f"Duplicate result for {ticket_id}.")
        issues = result.get("issue_types")
        if not isinstance(issues, list) or not issues or not all(isinstance(issue, str) and issue.strip() for issue in issues):
            raise ValueError(f"Invalid issue_types for {ticket_id}.")
        predictions[ticket_id] = issues

    by_intent = {intent: {"correct": 0, "scored": 0, "eligible": 0} for intent in INTENTS}
    mismatches = []
    missing = []
    for ticket_id, intent in sorted(EXPECTED.items()):
        if ticket_id in PENDING:
            continue
        counts = by_intent[intent]
        counts["eligible"] += 1
        if ticket_id not in predictions:
            missing.append(ticket_id)
            continue
        counts["scored"] += 1
        accepted = {normalize(label) for label in (intent, *INTENTS[intent][1])}
        issues = predictions[ticket_id]
        if any(normalize(issue) in accepted for issue in issues):
            counts["correct"] += 1
        else:
            mismatches.append({"ticket_id": ticket_id, "expected": intent, "actual": issues})

    return {
        "rubric": RUBRIC,
        "dataset_revision": REVISION,
        "metric": "expected_issue_type_present",
        "overall": {key: sum(counts[key] for counts in by_intent.values()) for key in ("correct", "scored", "eligible")},
        "by_intent": by_intent,
        "mismatches": mismatches,
        "missing": missing,
        "pending": [
            {"ticket_id": ticket_id, "source_intent": EXPECTED[ticket_id], "reason": reason}
            for ticket_id, reason in PENDING.items()
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="Reproduce and compare all 16 rows against the snapshot")
    verify.add_argument("--source", type=Path, help="Use a local copy of the pinned CSV")
    verify.add_argument("--output", type=Path, help="Also write a regenerated snapshot")
    prepare = commands.add_parser("prepare", help="Create the 14-ticket CLI input from the snapshot")
    prepare.add_argument("--output", type=Path, required=True)
    scoring = commands.add_parser("score", help="Score issue_types from a standard or audit CLI batch")
    scoring.add_argument("results", type=Path)
    scoring.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            if args.source:
                source = args.source.read_bytes()
            else:
                with urlopen(SOURCE, timeout=30) as response:
                    source = response.read()
            tickets = generate(source)
            generated = [ticket.model_dump() for ticket in tickets]
            snapshot_tickets()
            if generated != json.loads(SNAPSHOT.read_text(encoding="utf-8")):
                raise ValueError("Generated tickets do not match the committed snapshot.")
            if args.output:
                args.output.write_text(json.dumps(generated, indent=2) + "\n", encoding="utf-8")
            print(f"Verified {len(tickets)} BANKING77 test tickets at {REVISION} (CSV SHA-256 {CSV_SHA256}).")
        elif args.command == "prepare":
            ready = [ticket.model_dump() for ticket in snapshot_tickets() if ticket.ticket_id not in PENDING]
            args.output.write_text(json.dumps(ready, indent=2) + "\n", encoding="utf-8")
        else:
            result = score(json.loads(args.results.read_text(encoding="utf-8")))
            rendered = json.dumps(result, indent=2) + "\n"
            if args.output:
                args.output.write_text(rendered, encoding="utf-8")
            print(rendered, end="")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
