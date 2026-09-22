# Judge calibration

An uncalibrated judge is an unmeasured instrument. "We score 4.2/5" is not a
claim until you know how often the scorer agrees with a human — so this file
exists to hold that number, and to be honest when it hasn't been measured yet.

## Status

**Not yet calibrated.** Tier 2 has run zero graded batches. Until the table
below has rows, tier-2 scores are indicative and should not be quoted as
evidence of quality.

## Method

1. Run `python -m evals.run --tier2 --json > runs/<date>.json`
2. Take ten judgements. Score each yourself, blind to the judge's score —
   read the rubric and the answer, write your number, *then* look.
3. Record below. Agreement = exact match. Adjacent = within one point.
4. Investigate every disagreement of two points or more. The usual cause is a
   rubric that doesn't anchor its middle scores, not a defective judge.

## Results

| Date | Model | n | Exact | Adjacent | Notes |
|---|---|---|---|---|---|
| — | — | — | — | — | not yet run |

## Known limitations

- **Same model family judging and answering.** Shared blind spots are possible.
  Mitigated by keeping every factual question in tier 1, and by rubrics that
  name specific failure modes rather than asking for a general impression.
  Judging with a different family is the real fix; the cost trade is a
  deliberate choice, not an oversight.
- **Small n.** Twelve cases is a smoke test, not a benchmark. Grow the set as
  real org metadata arrives — and add a case every time a judgement surprises
  you, because a surprise is a rubric gap.
- **Temperature 0 is not determinism.** Identical inputs can still produce
  different scores. Re-run a disagreement before assuming the rubric is wrong.
