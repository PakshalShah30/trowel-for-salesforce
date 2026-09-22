# Golden dataset (Week 5)

Hand-verified question → expected-answer pairs about the dig site.

Tier 1 cases must agree with what `detectors.run_all` already returns for
`fixtures/dig-site` — the deterministic half is the reference answer, not a
second opinion on it.

Format (`cases.jsonl`, one per line):

```json
{"id": "dead-flow-01", "tier": 1, "question": "List every Active autolaunched Flow that nothing invokes", "expected": ["Orphan_Notifier"]}
{"id": "narrative-01", "tier": 2, "question": "Explain what happens when a Lead is created or updated", "rubric": "Must mention: LeadTrigger fires, Lead_Assignment writes Lead.Score__c, Shared_Utility runs as a subflow. Score 1-5 on accuracy, completeness, actionability."}
```

Rules:
- **Tier 1 (deterministic):** exact-match against graph/SQL truth. No LLM judging facts.
- **Tier 2 (LLM-as-judge):** rubric-scored narrative. Spot-check 10 judgments by hand and record your agreement rate in `calibration.md` — that number is interview gold.
- Every case must be verified BY YOU against the org before it enters this folder.
