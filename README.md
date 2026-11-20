# Support Ticket Triage Agent

A Python CLI that reads a Thai or English support conversation, calls tools through OpenAI GPT and returns a triage decision with supporting evidence.

Start with the [one-page design write-up](docs/architecture.md) for the architecture, failure handling and production evaluation plan. The [evaluation report](docs/evaluation-results.md) includes observed results and reproduction commands.

## Quick Start

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

### OpenAI key and model

Use a key from your OpenAI account or one authorized by the reviewer. Keep it out of Git.

**Windows PowerShell**

```powershell
$secureKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
Remove-Variable secureKey
```

**Bash on macOS/Linux**

```bash
read -rs -p "OpenAI API key: " OPENAI_API_KEY
echo
export OPENAI_API_KEY
```

The model defaults to `gpt-4.1-mini`. Set the optional `OPENAI_MODEL` environment variable to a compatible GPT model your account can access. [Environment variable reference](.env.example)

The CLI reads the shell environment directly. After you finish, clear the key with `Remove-Item Env:OPENAI_API_KEY` in PowerShell or `unset OPENAI_API_KEY` in Bash.

## Run and inspect a ticket

```bash
python -m triage_agent --all
triage-agent --ticket TICKET-002 --audit
python -m triage_agent --ticket-file tickets.json --output results.json
python -m pytest -q
```

The CLI accepts one ticket or an array in the [sample input format](src/triage_agent/data/tickets.json). The result includes urgency, product, issue types, sentiment, action, team, citations and a draft. Use `--audit` to compare GPT's proposal with the policy decision and inspect tool calls. Use `--no-trace` to omit tool arguments and results.

## How decisions are made

1. The [agent](src/triage_agent/agent.py) sends the full ticket and [system prompt](src/triage_agent/prompts/system.md) to GPT. It requires customer history and a knowledge-base lookup, then allows further investigation.
2. The [tools](src/triage_agent/tools.py) validate arguments, read fixture data and return evidence. Billing and system-status lookups help resolve payment and outage cases.
3. The [policy](src/triage_agent/policy.py) checks the structured proposal against the ticket and tool results. It can escalate an outage, route a reported defect or replace an unsupported draft. Automatic answers use approved FAQ text.

The offline suite runs without an API key. For live verification results and evaluation commands, see the [evaluation report](docs/evaluation-results.md).
