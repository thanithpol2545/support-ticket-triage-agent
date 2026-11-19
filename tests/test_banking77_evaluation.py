import pytest

from evaluation.banking77 import score, snapshot_tickets


def test_pilot_snapshot_keeps_all_rows():
    tickets = snapshot_tickets()
    assert len(tickets) == 16
    assert all(len(ticket.messages) == 1 for ticket in tickets)


def test_scoring_counts_aliases_misses_missing_and_pending_separately():
    report = score([
        {"result": {"ticket_id": "B77-TEST-0833", "issue_types": ["Card-Payment Fee Inquiry"]}},
        {"ticket_id": "B77-TEST-1627", "issue_types": ["duplicate_charge", "billing"]},
        {"ticket_id": "B77-TEST-1811", "issue_types": ["card transaction rejected"]},
        {"ticket_id": "B77-TEST-1094", "issue_types": ["unrecognized transaction"]},
    ])
    assert report["overall"] == {"correct": 3, "scored": 4, "eligible": 14}
    assert report["by_intent"]["pending_card_payment"] == {"correct": 0, "scored": 1, "eligible": 3}
    assert report["mismatches"] == [{
        "ticket_id": "B77-TEST-1627",
        "expected": "pending_card_payment",
        "actual": ["duplicate_charge", "billing"],
    }]
    assert len(report["missing"]) == 10
    assert {row["ticket_id"] for row in report["pending"]} == {"B77-TEST-1604", "B77-TEST-1815"}


def test_scoring_rejects_duplicate_and_pending_predictions():
    prediction = {"ticket_id": "B77-TEST-0833", "issue_types": ["card fee"]}
    with pytest.raises(ValueError, match="Duplicate"):
        score([prediction, prediction])
    with pytest.raises(ValueError, match="pending"):
        score([{**prediction, "ticket_id": "B77-TEST-1604"}])
