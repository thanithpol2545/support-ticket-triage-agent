# Engineering verification for the Ooca assignment

The review began from a clean `main` at `9e7e62eaa53effd03feca251719ceb7ba4d8f9d6`, verified against the private remote. The baseline passed 71 tests with 92% statement coverage on Windows Python 3.11.16. The original Word assignment was available locally. Independent QA confirmed that all 12 message texts and timestamps match the three supplied tickets and that their customer context was preserved. [Baseline Actions run](https://github.com/thanithpol2545/support-ticket-triage-agent/actions/runs/44243542984)

## A. Agent execution

All six native agents reviewed the same baseline. Architecture, QA, Security and DevOps also reviewed intermediate or final changes. The orchestrator implemented fixes on `codex/triage-final-verification`.

| Agent | Status | Work and evidence |
| --- | --- | --- |
| Architecture | SPAWNED | Traced proposal-to-policy flow. Reproduced false scope, joint incident evidence loss, sample-specific details, unrelated FAQ and malformed catalog problems. Cross-reviewed the patch with direct policy and simulated provider probes. |
| Python review | SPAWNED | Reproduced contrast-clause failures, overbroad scope, validation leakage, regional alias mismatch and the Windows cp874 failure. Used synthetic CLI and registry inputs. |
| AI engineering | SPAWNED | Passed 29 focused baseline tests. Reviewed official model and API documentation and made unauthenticated reachability probes. Reproduced GPT completion-status and schema error issues and verified the missing Typhoon schema contract. |
| Security | SPAWNED | Passed 28 focused baseline tests and 59 on the first patch. Independently verified account scoping, canned reply integrity, redaction and malformed KB handling. Follow-up probes identified negated relevance, blocked-tool accounting and locative negation cases. |
| QA | SPAWNED | Audited the source assignment and ran the complete suite in fresh environments. The final offline check passed 117 tests and 21 separate CLI scenarios, including nine targeted outage-scope cases. |
| DevOps | SPAWNED | Verified the private remote and baseline Actions. Clean installs from the source distribution and the wheel each passed all 117 tests, including a Python 3.12 run at the minimum dependency versions. |

## B. Findings

| ID and role | Severity and confidence | Baseline reproduction and impact | Resolution, test evidence and status |
| --- | --- | --- | --- |
| TRI-01 · Python, Architecture, QA, Security | P1 · High | “No issue before but now HTTP 500 for all employees” was low urgency. “Everyone else can log in. I get HTTP 500” was critical. The detector mixed scope across the thread and negation across contrast clauses, causing missed incidents and false escalations. | Bind scope to an affirmed symptom or explicit follow-up and keep locative negation intact. The first example is now critical and the second medium. English, Thai, cross-message, regional, universal and explicitly unaffected cases passed. **Fixed.** [Policy](../src/triage_agent/policy.py#L92) · [CLI regressions](../tests/test_e2e_regression.py#L89) |
| TRI-02 · Architecture, Python, QA | P2 · High | A joint duplicate charge and outage ran only billing diagnostics. A Europe report mentioned Asia, and scope alone produced sample-specific HTTP 500 and client-demo details. A disputed refund denial was classified low. | Run both relevant checks, preserve both issues, prioritize Infrastructure and derive descriptions from observed facts. Joint incident is critical, a disputed refund is high, and a refund-status inquiry remains low. **Fixed.** [Demo](../src/triage_agent/agent.py#L118) · [Regression tests](../tests/test_e2e_regression.py#L125) |
| TRI-03 · Security, AI, Architecture | P2 · High | A notification-email question received an Appearance draft after a model-selected search returned that FAQ. Matching the returned ID did not establish relevance. | Require an affirmed Appearance topic in the ticket before retaining that citation. Unrelated and explicitly negated examples route for review. A matching question still gets the approved draft with an untrusted excerpt present. **Fixed.** [Policy](../src/triage_agent/policy.py#L169) · [Regression tests](../tests/test_adversarial.py#L85) |
| TRI-04 · Security, Python, Architecture | P2 · High | A list-valued article ID was marked successful and then crashed citation collection. Duplicate IDs could identify conflicting text. Invalid arguments could expose values through tool errors. | Validate catalog fields and unique IDs before ranking, use sanitized tool errors and report only successful tools in `tools_used`. Malformed and duplicate catalogs return a tool error and produce no valid article IDs. Cross-account lookups still fail. **Fixed.** [Tool registry](../src/triage_agent/tools.py#L103) · [Tool tests](../tests/test_tools.py#L51) |
| TRI-05 · AI, Security, Python | P2 · High | Invalid model JSON fields and invalid ticket fields echoed synthetic private markers. GPT accepted a structured-looking final response with `incomplete` status. | Sanitize schema diagnostics and reject unsuccessful completion states. SDK transport tests verify named tool choices and returned tool results, and simulated timeouts, rate limits and invalid outputs fail safely. A partial batch leaves a previous output file intact. **Fixed.** [GPT adapter](../src/triage_agent/agent.py#L55) · [CLI](../src/triage_agent/cli.py#L54) · [SDK tests](../tests/test_agent.py#L119) |
| TRI-06 · AI, Architecture | P2 · High | Typhoon required strict local JSON but received no explicit output schema. A false `tool_calls` finish signal could be accepted as final JSON. | Give the model the shared schema in the trusted system message. Reject truncated, filtered and inconsistent completions. Added model and per-ticket latency to the optional evaluator. Mocked contract tests pass. Authenticated provider behavior is open. **Code fixed.** [Adapter](../src/triage_agent/typhoon.py#L58) · [Tests](../tests/test_typhoon.py#L61) |
| TRI-07 · DevOps, QA, Python | P2 · High | Full-trace JSON piped to cp874 exited 2 after writing the UTF-8 file. The source archive omitted the acceptance fixture and pytest setup. The first SDK test patch imported `httpx` unconditionally, which broke clean installs with newer SDKs. | Escape Unicode when the output stream cannot encode it, preserve UTF-8 on disk, package both test resources, and exercise the transport installed by the SDK. The cp874 regression compares parsed stdout and file output. **Fixed.** [CLI test](../tests/test_cli.py#L34) · [Manifest](../MANIFEST.in) · [SDK tests](../tests/test_agent.py) |
| TRI-08 · Python, DevOps | P3 · High | `asia` missed the mock record returned by `Asia`. | Use case-insensitive canonical region lookup and preserve aliases. Parameterized status tests pass. **Fixed.** [Registry](../src/triage_agent/tools.py#L131) · [Tool tests](../tests/test_tools.py#L30) |

## C. Test results

| Check | Command and evidence | Result |
| --- | --- | --- |
| Clean baseline install | `git clone`, `python -m pip install -e ".[dev]"`, `python -m pytest -q` on Windows Python 3.11.16 | 71 passed, 0 failed, 0 skipped |
| Updated suite and statement coverage | `uv run --no-project --python 3.11 --with pytest --with pytest-cov --with-editable . python -m pytest -q --cov=triage_agent --cov-report=term-missing` | 117 passed, 0 failed, 0 skipped. 513 of 553 statements covered, 93%. |
| Actual module CLI | `python -m triage_agent --mode demo --all` and individual `--ticket-file` subprocesses | 3 original and 9 synthetic cases passed. Each recorded a successful history lookup and KB search. |
| Compilation and packaging | `python -m compileall -q src scripts tests`, `uv build --python 3.11` and clean source-archive installation with the `dev` extra | Compilation passed. The wheel packages the prompt and four JSON resources. The extracted source archive includes its pytest fixtures and passed 117 tests. |
| Minimum requirements | Wheel installed on Python 3.12.16 with `openai==2.0.0`, `pydantic==2.8.0`, `pytest==8.0.0` | 117 passed. SDK mock transport checks also passed with OpenAI 3.55.1. |
| Write-up and secret scan | Rendered [the architecture write-up](architecture.md) to A4, counted pages and inspected the render. Scanned tracked Git history for common key formats. | One page. Zero matching commits. |
| GitHub Actions | Baseline on `main` and the reviewed change branch | Baseline success. The PR records checks for the reviewed commit. [Change branch workflow runs](https://github.com/thanithpol2545/support-ticket-triage-agent/actions/workflows/tests.yml?query=branch%3Acodex%2Ftriage-final-verification) |

### CLI acceptance

All rows below are deterministic CLI subprocess checks. The original labels are engineering expectations. A dash represents an edge fixture without a prescribed action. The input text and assertions for each synthetic case are version controlled. [Original inputs](../src/triage_agent/data/tickets.json) · [Synthetic inputs and expectations](../evaluation/adversarial_cases.json) · [CLI assertions](../tests/test_e2e_regression.py)

| Input | Expected urgency / action | Observed urgency / action |
| --- | --- | --- |
| TICKET-001 · Repeated charges during failed Pro upgrade | `high / escalate_to_human` | `high / escalate_to_human` |
| TICKET-002 · Enterprise coworkers cannot access the app, with HTTP 500 and green public status | `critical / escalate_to_human` | `critical / escalate_to_human` |
| TICKET-003 · Dark-mode defect and scheduling question | `medium / route_to_specialist` | `medium / route_to_specialist` |
| EDGE-001 · Charged twice | `high / escalate_to_human` | `high / escalate_to_human` |
| EDGE-002 · Charged four times on Free | `high / escalate_to_human` | `high / escalate_to_human` |
| EDGE-003 · Thai repeated charges after an unsuccessful upgrade | `high / escalate_to_human` | `high / escalate_to_human` |
| EDGE-004 · Company production access down | `critical / escalate_to_human` | `critical / escalate_to_human` |
| EDGE-005 · Thai organization-wide outage | `critical / escalate_to_human` | `critical / escalate_to_human` |
| EDGE-006 · Negated duplicate charges and docs request | `low / —` | `low / auto_respond` |
| EDGE-007 · Negated outage and Settings question | `low / —` | `low / auto_respond` |
| EDGE-008 · Untrusted refund instruction with affirmative duplicate charges | `high / escalate_to_human` | `high / escalate_to_human` |
| EDGE-009 · Appearance settings how-to | `low / —` | `low / auto_respond` |

### Assignment traceability

| Requirement | Verification |
| --- | --- |
| Exactly four urgency labels and three actions | Pydantic contract tests, all three sample decisions, and low-urgency edge cases. [Model tests](../tests/test_models.py) · [Policy tests](../tests/test_policy.py) |
| Product, issue type and sentiment | All original CLI outputs populated, plus evidence checks for simultaneous issues. [CLI tests](../tests/test_cli.py) · [Joint incident test](../tests/test_e2e_regression.py#L125) |
| Relevant KB answers and at least two tools | Thai and English lookup, no match, malformed records, relevance gate and actual registry execution with both demo and mocked OpenAI SDK. [Tool tests](../tests/test_tools.py) · [GPT tests](../tests/test_agent.py) |
| Working CLI, system prompt, tool definitions and write-up | Fresh install, sample outputs, Git history and a visually checked single-page write-up. [README](../README.md) · [System prompt](../src/triage_agent/prompts/system.md) · [Tool schemas](../src/triage_agent/tools.py) · [Architecture](architecture.md) |

### Real providers

| Provider | Evidence | Result |
| --- | --- | --- |
| OpenAI GPT | The documented default supports Responses, functions and Structured Outputs. An unauthenticated model request reached the API and returned HTTP 401. SDK transport tests used simulated responses. | **NOT VERIFIED.** No authorized `OPENAI_API_KEY` was configured. Authenticated inference, account model access and live ticket outputs remain open. [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini) |
| Typhoon | The public models endpoint returned HTTP 200 and listed `typhoon-v2.5-30b-a3b-instruct`. The tool guide demonstrates Chat Completions tool calls. | **NOT VERIFIED.** No rotated key was available through a secure mechanism. The authenticated tool loop, named `tool_choice` compatibility, classification consistency and latency remain open. [Typhoon tool calling](https://docs.opentyphoon.ai/en/tool/) |

## D. Independent fix verification

| Changes | Changed code | Independent review |
| --- | --- | --- |
| TRI-01, TRI-02 | `policy.py`, `agent.py` | Architecture, Security and QA replayed contrast, group-scope and joint-incident failures. QA's latest CLI and test runs passed after addressing its regional scope findings. |
| TRI-03, TRI-04, TRI-08 | `policy.py`, `tools.py` | Security verified negated topic rejection, typed KB failures and tool accounting. The final QA suite passed the case-insensitive status checks. |
| TRI-05, TRI-06 | `agent.py`, `cli.py`, `typhoon.py`, `scripts/evaluate_typhoon.py` | Architecture checked completion status handling. Independent QA verified the regression suite and the SDK mock transport on both SDK versions. |
| TRI-07 | `cli.py`, `MANIFEST.in`, `tests/test_agent.py` | DevOps verified cp874 output and fresh wheel and source-archive installs. QA verified the SDK transport switch in a fresh environment. |

## E. Final engineering verdict

**BLOCKED** on the mandatory authenticated OpenAI run. Automated and demo gates passed. Account configuration is still required for provider inference, and reviewer identities are needed to verify access to the private repository. Production accuracy requires a representative human-labeled evaluation.
