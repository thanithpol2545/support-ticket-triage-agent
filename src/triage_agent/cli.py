"""Minimal reviewer-friendly CLI: no UI, database, or cloud prerequisites for demo."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from pydantic import ValidationError

from .agent import AgentExecutionError, DemoTriageAgent, GPTTriageAgent, load_tickets
from .models import Ticket


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ooca support ticket triage agent")
    parser.add_argument("--mode", choices=["demo", "live", "typhoon"], default="demo", help="demo=deterministic, live=OpenAI GPT (required for submission), typhoon=optional evaluation")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ticket", help="Sample ticket ID (e.g., TICKET-001)")
    selection.add_argument("--all", action="store_true", help="Process all three supplied samples")
    selection.add_argument("--ticket-file", type=Path, help="Custom JSON ticket object or array")
    parser.add_argument("--output", type=Path, help="Write JSON output to this file")
    parser.add_argument("--no-trace", action="store_true", help="Hide full tool trace in printed JSON")
    args = parser.parse_args(argv)

    try:
        if args.ticket_file:
            raw = json.loads(args.ticket_file.read_text(encoding="utf-8"))
            tickets = [Ticket.model_validate(x) for x in (raw if isinstance(raw, list) else [raw])]
        else:
            tickets = load_tickets()
        if not tickets:
            raise ValueError("No tickets to process")
        if args.ticket:
            tickets = [t for t in tickets if t.ticket_id == args.ticket]
            if not tickets:
                raise ValueError(f"Unknown ticket ID: {args.ticket}")
        elif not args.all and not args.ticket_file:
            tickets = tickets[:1]

        if args.mode == "typhoon":
            from .typhoon import TyphoonTriageAgent
            agent = TyphoonTriageAgent()
        else:
            agent = GPTTriageAgent() if args.mode == "live" else DemoTriageAgent()
        results = []
        for ticket in tickets:
            result = agent.run(ticket).model_dump()
            if args.no_trace:
                result.pop("tool_trace", None)
            results.append(result)
        payload = results if len(results) != 1 or args.all or args.ticket_file else results[0]
        rendered = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except (ValueError, OSError, ValidationError, AgentExecutionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
