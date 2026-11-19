# Support Ticket Triage Agent Architecture

## Design

The CLI reads customer context and the full chronological ticket in Thai or English. A GPT model on the OpenAI Responses API calls `get_customer_history` and `search_knowledge_base` before proposing a decision. It can also query mock billing and regional status. The tools are read-only, validate arguments, scope account lookups to the current ticket and record their results. Python, the OpenAI SDK and Pydantic keep the workflow and its validation testable without an agent framework or database.

The model returns one of four urgency levels, the product, issue types, sentiment and an action. A shared policy validates FAQ references and applies deterministic safeguards. Widespread access failures go to Infrastructure, while repeated charges and refund disputes require Billing review. Individual access, payment and appearance failures require specialist diagnosis. Low-risk automatic drafts use approved FAQ templates. The CLI returns JSON with the decision, rationale and optional tool traces. A deterministic offline mode exercises the same tools and policy.

## Risks and safeguards

- **Unsupported claims.** Billing and status records are mock evidence. They cannot confirm a refund, regional incident or recovery time. Customer messages and FAQ excerpts are untrusted data. The policy removes unknown citations and checks for an affirmed appearance topic before using that template.
- **Provider and data failures.** Incomplete responses, invalid proposals, failed required tools and exhausted tool rounds produce errors. Failed optional tools prevent automatic replies. Human reviewers can investigate ambiguous language the policy misses.
- **Privacy and access.** Output is advisory and sends no customer messages. Full traces may include customer content. Production use requires authenticated account scoping, redaction, restricted access and retention controls.

## Production evaluation

Build a blinded, human-labeled dataset stratified by urgency, language, plan and how the ticket develops. Prioritize critical-incident recall and review every missed critical case. Track urgency macro-F1, extraction and routing accuracy, citation relevance, unsafe drafts and human overrides. Monitor latency, tool failures and token cost. Begin in shadow mode, then require human approval before testing automatic replies for verified low-risk questions.
