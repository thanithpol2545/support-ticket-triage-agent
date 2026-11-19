# Support Ticket Triage Agent

> **Ooca AI Engineer take-home assignment** · Python CLI · GPT + real function calling · read-only mock tools · safety-gated triage.

[![tests](https://github.com/thanithpol2545/support-ticket-triage-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/thanithpol2545/support-ticket-triage-agent/actions/workflows/tests.yml)

## 1. Purpose and assignment coverage

An AI agent that reads an **entire chronological customer-support ticket**, investigates relevant facts using tools, and recommends an appropriate support action. The original Word assignment is the source of truth; this table maps each requirement to implementation.

| Original requirement | Implementation | Verification |
|---|---|---|
| Classify urgency into **exactly** `critical / high / medium / low` | `Urgency` constrained type + decision policy | `tests/test_models.py`, `tests/test_policy.py` |
| Extract **product, issue type, customer sentiment** | `AgentProposal` and `TriageResult` Pydantic models | Schema and CLI tests |
| Search knowledge base for relevant **FAQs/docs** | `search_knowledge_base`, scored keyword retrieval of mock articles | `tests/test_tools.py` |
| Choose **auto-respond / route to specialist / escalate to human** | `Action` constrained type + deterministic safety policy | `tests/test_policy.py` |
| Use **at least two tools** | GPT is forced to invoke `get_customer_history`, then `search_knowledge_base`; optional billing/status tools | `tests/test_agent.py` verifies function calls and returned tool results |
| Working code on supplied tickets | CLI with three verbatim chronological threads | `python -m triage_agent --mode demo --all` |
| System prompt | `src/triage_agent/prompts/system.md` | Tracked in Git |
| Tool schemas + implementation (may be mocked) | `src/triage_agent/tools.py` | Contract tests |
| One-page architecture / failures / production evaluation | `docs/architecture.md` | Reviewer write-up |
| README with setup/run instructions; GitHub source | This repository | Quick Start below |

**Scoring criteria:** readability, maintainability, extensibility and logic. **No chat UI is required**; the terminal interface is intentional.

## 2. What is implemented (and what is not)

- **Live GPT mode:** uses OpenAI **Responses API**, function calling, structured JSON schema, Pydantic validation and safety policy. It requires `OPENAI_API_KEY` and network access. It has **not been live-verified with a real API key in this environment**.
- **Typhoon comparison mode:** optional **Chat Completions** function-call adapter for development testing. It does **not** substitute for the assignment-required OpenAI GPT mode. Tests with an injected fake client do **not** prove access to the real Typhoon API.
- **Demo mode:** fully deterministic, works **offline without an API key**, uses the same read-only local tools and deterministic safety policy. Demo outputs **are not GPT outputs** and are marked `"mode": "demo_rules"`.
- Four read-only mock tools: customer history, FAQ/KB lookup, billing status and system status. **No real charge/refund/incident** is executed or verified.
- Supports English and Thai customer messages; simple Thai keyword support in the local KB. GPT handles language understanding in live mode.
- Auto-respond, route and escalate are **recommendations/drafts only**; no real messages are sent.

## 3. Quick Start

Python **3.11+** is recommended. No Docker, DB server or UI is required.

```bash
git clone https://github.com/thanithpol2545/support-ticket-triage-agent.git
cd support-ticket-triage-agent
python -m venv .venv
```

Activate on **Windows PowerShell**:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on **macOS/Linux**:

```bash
source .venv/bin/activate
```

Install:

```bash
python -m pip install -e ".[dev]"
```

Run all three original tickets **without any API key**:

```bash
python -m triage_agent --mode demo --all --no-trace
```

Run one sample with full tool trace:

```bash
python -m triage_agent --mode demo --ticket TICKET-002
```

Save the sample results:

```bash
python -m triage_agent --mode demo --all --output sample_outputs/demo_results.json
```

### Live GPT mode

Use an API key **from your own OpenAI account or a key supplied by the reviewer**. **Never commit it.**

**Windows PowerShell**:

```powershell
$secureKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
Remove-Variable secureKey
$env:OPENAI_MODEL="gpt-4.1-mini"
python -m triage_agent --mode live --all --no-trace
Remove-Item Env:OPENAI_API_KEY
```

**macOS/Linux**:

```bash
read -rs -p "OpenAI API key: " OPENAI_API_KEY; echo
export OPENAI_API_KEY
export OPENAI_MODEL="gpt-4.1-mini"
python -m triage_agent --mode live --all --no-trace
unset OPENAI_API_KEY
```

`OPENAI_MODEL` can be changed to a compatible GPT model accessible to your account. `.env.example` documents the variables; the app reads **environment variables directly** and does not automatically load `.env`.

OpenAI has announced retirement of the `gpt-4.1-mini-2025-04-14` snapshot on January 14, 2027. Check the provider's model lifecycle before choosing a deployment model. [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations)

### Optional Typhoon evaluation (not a replacement for OpenAI GPT)

Typhoon documents its OpenAI-compatible Chat Completions endpoint at `https://api.opentyphoon.ai/v1` and model `typhoon-v2.5-30b-a3b-instruct`. Its request format differs from the OpenAI GPT **Responses API** used for the assignment, so a separate adapter lives in `src/triage_agent/typhoon.py`. Never place a real key in source code, a repository, a GitHub workflow input, an issue, or a test fixture.

**PowerShell** (set key locally, without saving it to the repository):

```powershell
$secureKey = Read-Host "Typhoon API key" -AsSecureString
$env:TYPHOON_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
Remove-Variable secureKey
python -m triage_agent --mode typhoon --all --no-trace
python scripts/evaluate_typhoon.py --include-edge --limit 12
Remove-Item Env:TYPHOON_API_KEY
```

**Bash**:

```bash
read -rs -p "Typhoon API key: " TYPHOON_API_KEY; echo
export TYPHOON_API_KEY
python -m triage_agent --mode typhoon --all --no-trace
python scripts/evaluate_typhoon.py --include-edge --limit 12
unset TYPHOON_API_KEY
```

The optional evaluation fixture includes the 3 supplied tickets and 9 synthetic boundary cases. The harness reports the configured model, predicted labels, decisions, tools, policy overrides and per-ticket latency. Synthetic labels are proposed test expectations. Typhoon's public model list includes the configured model. Authenticated inference and named tool-choice support remain unverified in this review because a securely configured key was unavailable. [Typhoon models](https://docs.opentyphoon.ai/en/models/) · [Typhoon tool calling](https://docs.opentyphoon.ai/en/tool/)

**Alternative network-enabled test:** In GitHub, configure **Settings → Secrets and variables → Actions → New repository secret** named `TYPHOON_API_KEY` (use a newly generated key). Then open **Actions → typhoon-real-api-smoke → Run workflow**. The manual workflow uses the repository secret, not a public workflow input, and runs three real-provider sample tickets by default. Do not place credentials into the Run Workflow form.

### Tests

```bash
python -m pytest -q
```

The test suite uses **fake OpenAI/Typhoon clients** to validate function-call orchestration without credentials. `tests/test_e2e_regression.py` exercises all 9 synthetic edge cases through the CLI, plus Thai and English contrast clauses, single-user failures, wider incidents, simultaneous outage and billing reports, refund disputes and input errors.

See [the engineering review](docs/qa-review.md) for the baseline, regression results, packaging checks and open live-provider gates. Coverage reporting uses the optional local `pytest-cov` package.

### Custom ticket input

```bash
python -m triage_agent --mode demo --ticket-file my_ticket.json
python -m triage_agent --mode live --ticket-file my_ticket.json
```

`my_ticket.json` is a single `Ticket` object or a non-empty array of `Ticket` objects (see `src/triage_agent/data/tickets.json`). Empty arrays, malformed tickets and unknown ticket IDs return a non-zero exit code rather than generating a misleading successful result.

## 4. Architecture

```mermaid
flowchart TD
    A[Customer profile + chronological messages] --> B[GPT Responses API agent]
    B --> C[Read-only function tools]
    C --> D[Mock profile / KB / billing / status]
    D --> B
    B --> E[Strict structured JSON + Pydantic]
    E --> F[Deterministic safety policy]
    F --> G{Next action}
    G --> H[Auto-respond draft]
    G --> I[Route to specialist]
    G --> J[Human escalation]
    F --> K[JSON result + tool trace]
```

Two mandatory tool calls are explicitly requested through `tool_choice`, first `get_customer_history`, then `search_knowledge_base`. The model may invoke billing or status tools before returning its structured proposal. The resulting proposal is always checked by `finalize()`; policy can **raise urgency and escalate**, reject invented KB references and prevent unsafe auto-responses. It cannot make a refund or outage diagnosis true.

### Tool inventory

| Tool | Input | Source / safety |
|---|---|---|
| `get_customer_history` | `customer_id` | Current ticket's mock profile, customer ID restricted |
| `search_knowledge_base` | `query` | Ranked local JSON FAQs with verifiable `KB-*` article IDs |
| `check_billing_status` | `customer_id` | Mock record only; **bank-side charges unverified** |
| `check_system_status` | `region` | Mock public status and regional diagnostics, no confirmed incident |

Tool definitions use strict JSON function schemas; every invocation is recorded with its arguments, result and success status. All tools are **read-only**, validate arguments and reject unknown tools. There is a maximum model/tool round limit.

### Output contract (excerpt)

```json
{
  "ticket_id": "TICKET-002",
  "urgency": "critical",
  "product": "Enterprise platform",
  "issue_types": ["http_500", "access_failure"],
  "sentiment": "frustrated",
  "action": "escalate_to_human",
  "assigned_team": "Infrastructure / On-call",
  "kb_article_ids": ["KB-002"],
  "tools_used": ["get_customer_history", "search_knowledge_base", "check_system_status"],
  "policy_overrides": [],
  "mode": "demo_rules"
}
```

This is an **illustrative excerpt**, not a live model result. Actual output additionally includes `summary`, `reasons`, `draft_response`, `uncertainties` and optionally `tool_trace`.

## 5. Supplied test scenarios and expected behavior

| Case | Description | Target baseline | Rationale |
|---|---|---|---|
| `TICKET-001` | Free user: failed Pro upgrade, repeated reported charges, deadline | **high**, `escalate_to_human`, Billing | Financial dispute must be reviewed; bank/refund state unknown |
| `TICKET-002` | Enterprise, Thailand, 45 seats: multi-user HTTP 500 and client demo | **critical**, `escalate_to_human`, Infrastructure | Broad access failure despite green public status; affected-user count unknown |
| `TICKET-003` | Pro: dark-mode setting malfunction and scheduling idea | **medium**, `route_to_specialist`, Product | Separate confirmed-reported defect from unconfirmed feature availability |

These labels are **proposed test baselines**, not ground truth provided by Ooca. `low` is tested separately for straightforward questions to cover **all four required urgency values**.

## 6. Safety and failure handling

- **Repeated charges:** never assert that money was captured or a refund issued without evidence; escalate to Billing.
- **Enterprise outage:** escalate a multi-user HTTP 500; a green status page is not proof that the tenant is functioning. The enterprise has **45 seats**, not 45 proven affected people.
- **Appearance defects:** route to a specialist if System Default does not work; don't invent scheduled dark-mode availability.
- **Missing/unverified KB:** discard invented article IDs and Appearance citations for unrelated tickets. Low-risk auto-response uses an approved template. The general template asks for clarification.
- **Tool failure:** fail closed rather than invent a success; malformed KB data returns a tool error and prevents auto-response.
- **Critical:** force human escalation, even if the model suggested only a specialist route.
- **Language variants and scope:** demo and policy share English and Thai incident checks. Affirmative group impact, including an explicit follow-up about the same error, is required for a multi-user outage. The heuristics cover selected phrasing. Review ambiguous reports and model outputs on labeled data.
- **Single-user failures:** a first failed upgrade or access issue is at least `medium` and routed to a specialist; widespread outages remain `critical`.
- **API failure, malformed JSON, wrong customer ID, max tool rounds:** return a visible error and stop instead of silently fabricating a triage result.
- **Untrusted content:** customer messages and KB passages are data; the system prompt forbids obeying instructions embedded in them. This is a prompt-layer mitigation, not a guarantee against every injection.
- **Privacy:** schema diagnostics omit raw validation values. Full traces and result fields may include customer data. `--no-trace` omits tool arguments and results. Before connecting real account records, implement authorization, access controls, redaction and retention.

## 7. Project structure

```text
src/triage_agent/
  __main__.py              # CLI module entry
  cli.py                   # args / JSON / exit codes
  models.py                # Pydantic contracts + JSON schema
  agent.py                 # GPT function-call loop + offline demo
  tools.py                 # four mock tools + schemas
  policy.py                # deterministic escalation safety rules
  prompts/system.md        # AI system prompt
  data/                    # original 3 ticket threads + mock data

tests/                     # model, tool, policy, agent, CLI, E2E regression, adversarial, Typhoon fake-client tests
src/triage_agent/typhoon.py # optional Typhoon evaluation adapter
evaluation/                # proposed synthetic edge-case dataset
scripts/evaluate_typhoon.py # manual real-provider test runner
docs/architecture.md       # assignment-required one-page write-up
docs/qa-review.md          # reviewer-style design risks and acceptance gates
.github/workflows/tests.yml
.env.example
pyproject.toml
```

## 8. Production evaluation and limitations

See `docs/architecture.md` for the **one-page submission write-up**. In a real rollout, use human-labeled ticket sets (including Thai/English), evaluate **critical recall**, macro-F1 for urgency, routing accuracy, unsafe auto-response rate, grounded KB citation rate, tool failure rate, latency and token cost. Review false negatives in critical/billing tickets first. Add confidence-based handoff, monitoring, access control and redaction before production.

**Known limitations:** tiny mock knowledge base, heuristic offline keyword retrieval, three provided sample tickets, no live billing/monitoring integrations, no live OpenAI API call performed in this workspace. Do not infer real-world reliability from the local unit test count.

## 9. Submission checklist

- [x] All five assignment functional requirements represented in runnable code
- [x] Three original chronological sample ticket fixtures
- [x] OpenAI GPT tool-calling implementation, no API key embedded
- [x] Version-controlled system prompt and function tool schemas
- [x] CLI, Pydantic validation, deterministic safeguards and offline tests
- [x] One-page architecture / risks / production evaluation write-up
- [x] Full-path regression tests for original tickets, 9 additional synthetic cases, Thai/English negation, empty inputs and safe provider errors
- [ ] **Live API smoke test with an authorized `OPENAI_API_KEY`**
- [ ] **Real Typhoon provider smoke test** (optional; requires network and user-managed key)
- [ ] Confirm reviewer access to private GitHub repository

---

**Documentation sources:** [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling) · [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
