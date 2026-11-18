# Engineering Review & Regression Evidence — 2026-11-18

This is an engineering review of the existing repository, not a claim of native independent sub-agent execution. The original Ooca Word assignment is the source of truth. No production integrations or customer notifications are connected.

## Baseline and confirmed defects

- Remote baseline inspected: `main` at `f9dd93a161d905c3b83e2eee1ce5c94ee7a48bc8` (private).
- Before changes: 47/47 local pytest tests passed, 91% statement coverage; only 10/12 offline acceptance scenarios passed.
- **EDGE-006**: "no duplicate charges" was escalated high by Demo's naive `charge` keyword branch.
- **EDGE-007**: "no HTTP 500 issue" was escalated critical by Demo's naive `500` keyword branch.
- Further tests found Thai combining marks were not consumed by the negation lookbehind regex; "ไม่ได้ขึ้น error 500" was falsely escalated.
- Additional gaps found: initial failed upgrade and single-user HTTP 500 were classified low; `[]` input returned success; provider error text could expose request metadata.

## Fixes, validation and result

| Item | Mitigation | Regression evidence |
|---|---|---|
| English/Thai negations | One shared `risk_signals` detection path in Demo and safety policy; Thai Unicode marks accepted in negation window | `tests/test_e2e_regression.py` |
| Single-user access/payment | Minimum medium severity; route to Technical or Billing Support without assuming widespread incident | `test_individual_failure_is_routed_not_auto_closed` |
| Confirmed large incidents | Existing critical outage/repeated-billing escalation preserved | 3 supplied tickets, EDGE-001..005/008, positive-after-negation tests |
| Empty input | Reject empty ticket batch with nonzero CLI status | `test_empty_input_is_rejected_without_success_message` |
| Provider errors | Avoid raw OpenAI SDK exception text in CLI/API errors | `test_provider_error_does_not_leak_secret_or_request_content` |
| Customer tools, grounding, structured output | Existing safety checks preserved | `test_tools.py`, `test_agent.py`, `test_policy.py`, `test_typhoon.py` |

**Executed:** `PYTHONPATH=src python -m pytest -q --cov=triage_agent --cov-report=term-missing`

**Local result:** 71 passed; 92% line coverage (Python 3.13.5, Linux); original 3 + nine synthetic scenarios = 12/12 offline demo acceptance passed.

**Limitations:** Package installation from a fresh internet-connected machine is not reproducible in this isolated runtime because external DNS and package downloads are unavailable. GitHub CI can verify installation on its runner. Neither real OpenAI GPT nor real Typhoon API inference was executed; no authorized rotated API credentials were available. Synthetic labels are assumptions, not adjudicated human ground truth. Risk of ambiguity outside tested patterns remains.

## Reviewer checks / next gate

- Verify GitHub Actions on the new commit and README setup from a clean machine.
- Run live GPT with an authorized `OPENAI_API_KEY` against the three supplied threads and edge cases.
- Optionally run the Typhoon workflow with a **new rotated** `TYPHOON_API_KEY` stored only as a repository secret.
- Confirm recruiting-team access to this private repository.
- Do not interpret successful code tests as production classification accuracy.
