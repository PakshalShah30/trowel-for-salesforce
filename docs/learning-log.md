# Learning log

Five bullets a week, minimum. What you learned, what surprised you, what broke.
These become LinkedIn posts and interview answers. Raw is fine.

## Week 1 — (date)
-

## Week 2 — (date)
-

## Week 3 — catalog, graph, first detectors

Five things worth being able to say out loud:

1. **Record-triggered Flows carry `processType: AutoLaunchedFlow` too.** The only
   thing separating them from a genuinely callable autolaunched Flow is
   `<start><triggerType>`. Branch on processType alone and the detector flags
   every working record-triggered Flow in the org — which is how a dead-code
   tool loses its credibility in the first five minutes.

2. **Graph vs SQL isn't about one hop, it's about the second one.** "What
   directly writes this field" is a join. "What breaks if I delete it" walks the
   Flow that writes it, the Flow that calls that one, the Apex behind that, the
   trigger behind that. Recursive CTE with a guessed depth, or `nx.descendants`.

3. **Deterministic first, model second.** "Zero inbound references" has a
   correct answer that two people can settle by counting, so it gets code and a
   unit test. What the finding *means for this org* and which of forty to fix
   first have no ground truth, so they get a model. The line between them is
   also the line between Tier 1 and Tier 2 evals.

4. **Apex regex has a hard ceiling, and the honest move is to stop at it.** It
   reliably finds `Flow.Interview.X` and `FROM Object`. It cannot tell whether
   `lead.Status = 'X'` executes, or whether `lead` is even a Lead. Field-conflict
   detection built on that is a false-positive generator; it needs the Tooling
   API's SymbolTable, so it waits.

5. **False negatives are worse than false positives here.** A false positive
   gets investigated and dismissed. A false negative is silence — nothing
   surfaces to investigate. That's why the commented-out `Flow.Interview` call in
   the fixture has a test of its own: if the comment stripper regressed, a truly
   dead Flow would quietly stop being reported.

Severity carries the honesty. TRW002 is `info`, not `medium`, because reports,
list views, layouts and integrations sit outside retrieved metadata and any of
them could be the consumer. It's a shortlist for an admin's afternoon, not a
verdict — and saying so in the finding is the difference between a tool people
trust and one they mute.
