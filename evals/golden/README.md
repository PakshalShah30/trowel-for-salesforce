# Golden dataset (Week 5)

Hand-verified question → expected-answer pairs about the seeded dig-site org.

Format (`cases.jsonl`, one per line):

```json
{"id": "dead-flow-01", "tier": 1, "question": "List all Flows with zero inbound references and zero runtime interviews", "expected": ["Old_Lead_Router", "Legacy_Discount_Calc"]}
{"id": "narrative-01", "tier": 2, "question": "Explain what happens when a Lead is converted", "rubric": "Must mention: trigger X fires, Flow Y updates Lead.Status, field mapping to Opportunity. Score 1-5 on accuracy, completeness, actionability."}
```

Rules:
- **Tier 1 (deterministic):** exact-match against graph/SQL truth. No LLM judging facts.
- **Tier 2 (LLM-as-judge):** rubric-scored narrative. Spot-check 10 judgments by hand and record your agreement rate in `calibration.md` — that number is interview gold.
- Every case must be verified BY YOU against the org before it enters this folder.
