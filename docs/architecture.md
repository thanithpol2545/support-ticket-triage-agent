# Architecture, Risks & Evaluation (one-page write-up)

**Assignment:** Support Ticket Triage Agent · **Design:** one GPT agent, four read-only mock tools, strict output contract, deterministic safety gate. No UI or production integrations.

## Architecture and rationale

1. **Input:** customer plan/tenure/region/seats plus the full chronological message thread (English or Thai). This preserves urgency escalation across repeated contacts.
2. **Analysis:** OpenAI Responses API with function calling. Two named tools are mandatory: `get_customer_history` and `search_knowledge_base`; the model can additionally call `check_billing_status` or `check_system_status`. Strict tool schemas, customer ID scoping and a bounded call loop keep behavior auditable. All external data is mocked and read-only.
3. **Decision:** the model proposes `urgency` (**critical/high/medium/low**), `product`, `issue_types`, `sentiment` and one action (**auto_respond/route_to_specialist/escalate_to_human**). Pydantic rejects invalid fields or values. Code then enforces safety floors: multi-user outage → **critical + escalate**; repeated billing charges → **at least high + escalate**; reported dark-mode malfunction → **at least medium + route**; individual failed payments or access problems → **at least medium + route**. The policy forces critical-to-human escalation, removes unverified KB citations, and replaces all low-risk auto-responses with approved FAQ-only templates (never verbatim model text). The result includes a responsible team, evidence summaries, uncertainties and a tool trace.
4. **Why this stack:** Python, OpenAI SDK, Pydantic and pytest make the solution readable, testable and extensible without an unnecessary agent framework, frontend or database. Tool classes can later be replaced with authorized real services while keeping the interface stable.

## Risks and mitigations

- **Hallucinations/unsafe commitments:** never claim captured charges, successful refunds, confirmed regional outages or feature availability without tool evidence; route uncertain high-risk cases to humans.
- **Prompt injection / privacy:** ticket content and documents are untrusted; strict tool argument validation and customer scoping prevent obvious cross-account access. Production needs stronger permission checks, PII redaction and retention rules.
- **Failures / false negatives:** invalid JSON, API timeout, bad tool output and tool-loop limits fail visibly instead of auto-responding. Human escalation is preferable where severity or evidence is uncertain.
- **Mock limitations:** local KB, billing and status records cannot prove real-world correctness. An offline demo is explicitly labeled `demo_rules`, never presented as a live GPT test.

## Production evaluation

Build a blinded human-labeled dataset stratified by severity, plan, language and multi-message progression. Measure **critical recall** (primary safety metric), four-class urgency macro-F1, issue extraction F1, routing accuracy, grounded FAQ citation rate, unsafe auto-response rate, and human override rate. Track tool errors, latency and token cost; review high-severity false negatives weekly. Begin with a shadow deployment (no outgoing customer messages), then human-approved suggestions before selectively enabling low-risk auto-replies. Use drift and incident feedback to revise policies and regression tests.
