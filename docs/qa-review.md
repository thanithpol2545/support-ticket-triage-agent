# Pre-build Software/AI Engineer & QA Design Review

This review captures two **perspectives** applied during development; it does not claim independently spawned agents ran in this environment.

| Area | Engineer decision | QA acceptance criterion |
|---|---|---|
| Requirements | Word assignment remains source of truth | Urgency enum has exactly 4 classes, next-action enum exactly 3, extraction includes product/issue/sentiment |
| Agent | Single GPT Responses API function-call loop | Fake SDK integration verifies actual tool calls and tool outputs return to model |
| Retrieval | Small explicit mock KB with grounded article IDs | Reject hallucinated KB IDs and safely handle no matching article |
| Tool safety | Read-only, strict schemas, customer scoped | Cross-customer reads and unknown tools return errors |
| Business policy | Severity floors on outage/billing/defect | Critical and repeated-charge cases cannot auto-respond |
| Observability | Tool traces, reasons, uncertainties | Output has exact mode, tool names and decisions |
| Evaluation | pytest and human-labeled production plan | Tests do not masquerade as real model benchmark |

## Open items before submission

1. Run at least one genuine GPT live API call with an authorized key to verify model/schema/tool behavior against a real endpoint.
2. Confirm reviewer access to the private repository; add a reviewer only when the recruiting team provides the account/access instructions.
3. Capture actual live outputs and, if possible, do a reviewer-style clean-machine install.

**Scope intentionally excluded:** frontend, live refunds, real notifications, production monitoring, database, prompt/agent frameworks beyond the official SDK.
