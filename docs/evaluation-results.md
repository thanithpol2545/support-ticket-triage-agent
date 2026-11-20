# Evaluation results

## Submission verification

The Python CLI passed **3/3 supplied OOCA tickets** and **20/20 synthetic challenge cases** on implementation commit `feb0f27`, using OpenAI Responses API model `gpt-4.1-mini-2025-04-14`. All 23 tickets completed the required customer-history and knowledge-base lookups using project fixtures. The same 20 challenge cases scored 11/20 on `5f06d22` under the same rubric. Independent offline QA passed 9 language probes and 4 access-routing controls. The full suite passed 260 tests.

The change distinguishes reported individual access failures from outages with confirmed group impact. It preserves the latest reported status in handoff drafts and attributes pending charges and refund updates to customer evidence. The challenge set is a development set used to find regressions. Results measure those cases and their specified criteria. Model-generated internal summaries may still need human review before use in production.

## Earlier live evaluation

On commit `3a63297`, the Python CLI called the OpenAI Responses API with `gpt-4.1-mini-2025-04-14`. The seven distinct tickets below passed their acceptance criteria. Every ticket completed both customer-history and knowledge-base calls. The tools used repository fixtures. The full offline suite passed 229 tests.

| Live case | Observed final decision or draft |
|---|---|
| TICKET-001 | High, escalated to Billing Support. Charges and refunds remain unverified. |
| TICKET-002 | Critical, escalated to Infrastructure / On-call. Regional scope and recovery time remain open. |
| TICKET-003 | Medium, routed to Product Support. Scheduled dark mode remains unconfirmed. |
| P05A | The draft distinguishes repeated attempts to pay from confirmed charges. |
| P07B | The System Default defect is routed to Product Support at medium urgency. |
| P11A | The notification question is routed to General Support without Appearance advice or a citation. |
| P11B | The dark-mode question receives the approved Appearance guidance from KB-003. |

Independent live runs repeated P05A/P07B and P11A/P11B. P11A still retrieves an irrelevant appearance article for some queries. The handoff case where the initial GPT proposal already cites that article was verified by offline replay.

## Reproduce

Run these commands from the repository root after following the README setup. Only the triage CLI calls OpenAI.

```bash
python -m pytest -q
python -m triage_agent --all --audit --output ooca-audit.json
python -m evaluation.paired prepare --output pairs.json
python -m triage_agent --ticket-file pairs.json --audit --output pairs-audit.json
python -m evaluation.paired model-queries pairs-audit.json
```

## Extended evaluation

The earlier 46-ticket live run on `b66052b` scored 9/9 edge urgency targets and 6/6 specified actions. Direct customer queries retrieved the expected FAQ in the top three for 3/5 cases. GPT-generated queries did so for 4/5. The [paired rubric](paired-scoring-rubric.md) records the scoring criteria for the additional development cases.

The external BANKING77 pilot measured issue types. GPT scored 6/14 eligible tickets under the fixed synonym rubric. Two ambiguous labels were excluded. The pilot includes 16 English test examples from the [PolyAI dataset at the pinned revision](https://github.com/PolyAI-LDN/task-specific-datasets/tree/57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data), distributed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The original utterances were preserved and converted from CSV to ticket JSON. Credit to Iñigo Casanueva, Tadas Temčinas, Daniela Gerz, Matthew Henderson and Ivan Vulić, [Efficient Intent Detection with Dual Sentence Encoders](https://aclanthology.org/2020.nlp4convai-1.5/).

```bash
python -m evaluation.banking77 verify
python -m evaluation.banking77 prepare --output banking77.json
python -m triage_agent --ticket-file banking77.json --audit --output banking77-audit.json
python -m evaluation.banking77 score banking77-audit.json
```
