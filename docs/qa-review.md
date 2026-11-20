# QA Evidence for the Ooca Assignment

This review covers the OpenAI-only CLI based on main commit `2a07a65a966818b7091a35c34ed975876b54c355`. Every supported ticket selection calls the same GPT agent. The Responses API supplies a proposal after two successful required tool calls. Pydantic validates it before the shared safety policy selects the final action.

## Verification

| Check | Evidence |
|---|---|
| CLI entry points | The module and installed console command accept the documented ticket selectors. The tests cover default selection, sample IDs, single-ticket JSON, ordered JSON batches, UTF-8 files and trace suppression. [CLI tests](../tests/test_cli.py) |
| CLI failures | The retired selector is rejected. A missing or blank key returns exit code 2 with shell setup guidance and produces no result. Invalid input and a provider failure during a batch also produce no result. [CLI tests](../tests/test_cli.py) |
| OpenAI contract | Fake clients and an SDK mock transport verify required history and KB dispatch and correlation by `call_id`. Missing or failed required calls, invalid proposals, timeout, rate limits and exhausted rounds fail safely. [Adapter tests](../tests/test_agent.py) |
| Original ticket targets | All three tickets pass the mock-backed CLI check. TICKET-001 is `high / escalate_to_human` to Billing Support, TICKET-002 is `critical / escalate_to_human` to Infrastructure / On-call, and TICKET-003 is `medium / route_to_specialist` to Product Support. [CLI tests](../tests/test_cli.py) |
| Edge fixtures and safety | All nine urgency expectations and the six explicitly defined action expectations are enforced in mock-backed CLI tests. Other cases cover approved FAQ citations, negation, and refusal to use arbitrary model text for automatic replies. [Fixtures](../evaluation/adversarial_cases.json) · [Regression tests](../tests/test_e2e_regression.py) |
| Outage scope | The PR #3 regressions test affirmative multi-user reports, lone users, denied impact, questions about scope and requests for help after a positive report. Both the mock-backed CLI and direct policy checks use simulated low-urgency proposals. The regional status lookup is tested separately as an optional model tool choice. [Policy tests](../tests/test_policy.py) · [Regression tests](../tests/test_e2e_regression.py) |
| Fresh wheel | A clean Windows environment ran both installed entry points against a local simulated Responses API. The three documented commands produced six ticket results with both required tool calls for each ticket. Both entry points rejected the retired selector and returned exit code 2 with an absent key. |
| Full offline suite | `python -m pytest -q` passed 139 tests on Windows with Python 3.11.16. CI installs the package, runs pytest and checks help from both entry points. |

The original ticket outcomes and synthetic fixture expectations are project acceptance targets. The offline tests verify behavior under supplied proposals. Model classification quality and provider access require authenticated evaluation.

## Authenticated OpenAI

The original offline review had no authorized key. A later authenticated run on `b66052b` processed all 46 evaluation tickets through the CLI, including the three original tickets. [Evaluation results](evaluation-results.md)

To validate a newer commit, configure an authorized key using the [README](../README.md#openai-key-and-model) and run `python -m triage_agent --all --no-trace`. Compare all three results with the targets and confirm both required tool names for each ticket. Review extraction, citations and draft safety locally. Record ticket ID, configured model, successful tool names, urgency, action and policy overrides as evidence.

## Follow-up observations

Prior QA observed that a specialist draft can retain a password request, four edge queries missed a relevant article when their text was used verbatim, and the appearance summary in the prior acceptance run omitted the System Default reproduction detail. Review draft text, retrieval recall and extraction during live evaluation. Reviewers need access to the private repository independently of these technical checks.

## 2.1 External evaluation pilot

The [BANKING77 pilot report](external-evaluation-pilot.md) documents the source, 16 sampled tickets and the scoring plan for `issue_types`. The authenticated baseline scored 6 of 14 tickets under that plan. Two await human label review. [Evaluation results](evaluation-results.md#4-banking77-pilot)

The [reproducible evaluation report](evaluation-results.md) records the later baseline comparison, retrieval probes and reviewer commands.
