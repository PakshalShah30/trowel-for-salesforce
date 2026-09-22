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

## Week 5 — evals, and the harness that caught itself

The two-tier split is the whole argument, and it's also the answer to the
objection people raise about LLM-as-judge. The objection — *isn't it circular
to have a model grade a model?* — is real when the question is factual: both
can be wrong in the same direction and the score still looks fine. It doesn't
apply if facts never reach the judge. "Which Flows does nothing invoke" is a
set comparison. What the judge grades is whether a piece of prose explains a
Flow well, which is a question about writing, and writing is a thing models
are actually qualified to assess.

The practical constraint I didn't expect to matter this much: **cost is a
design input for evals.** Tier 1 needs no API key, so it runs on every pull
request including from forks, in 0.3 seconds, for nothing. That's why it's the
tier that blocks merges. An eval gate that's expensive gets made optional, and
an optional gate isn't a gate.

**Mutation testing is the part I'd lead with.** A green eval suite proves
nothing on its own — cases that assert something trivially true look identical
to cases that work. So five plausible mistakes get applied deliberately, and
each has to break at least one case: dropping Apex parsing, skipping comment
stripping, branching on processType instead of triggerType, collapsing edge
types, and treating impact analysis as a single join. A surviving mutation
exits 2 and names the hole in the dataset.

And the first run caught a bug **in the harness itself**. `processtype-only`
reported as surviving. The eval suite was fine — my mutation was applying its
monkeypatch and restoring it in a `finally` *before* returning the world, so
the patch was long gone by the time the detectors ran. It was testing nothing
and reporting that as a gap in the suite. Mutations are context managers now,
with evaluation inside the `with` block.

Two things I take from that. First, a failing result that points at the wrong
component is still a useful result — it was right that something was broken.
Second, and less comfortable: I'd have believed a clean green table. The only
reason the bug surfaced is that a tool built to be suspicious of green got
pointed at its own output.

Calibration is written down as **not yet done**, which is the honest state:
tier 2 has run zero graded batches. A judge whose agreement rate nobody has
measured is an unmeasured instrument, and "we score 4.2" isn't a claim until
that number exists. `calibration.md` holds the method and an empty table
rather than a vague promise.
