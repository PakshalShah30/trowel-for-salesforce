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

## Week 4 — hybrid retrieval, and a fixture that didn't say what I thought

The checkpoint question was *"when would pure vector RAG give a wrong answer
here that hybrid gets right?"* I wanted the answer to be an eval case, not a
paragraph.

1. **My go-to example was wrong, and the fixture showed it.** I'd been
   saying "Shared_Utility is two hops from Score__c." It isn't. It filters on
   Score__c directly, so it's one hop, and its card mentions the field by
   name. graph-01's `guards` text said the same wrong thing, and in hindsight
   the clue was already there: `direct-dependencies-only` never broke
   graph-01. On the fixture as it was, pure vector retrieval found every
   dependent of Score__c, so the checkpoint question had no honest answer
   yet. The fix was to give the empty `Apex_Invoked_Flow` a lookup filtered
   on Score__c. Now `LeadService → Apex_Invoked_Flow → Score__c` is a real
   two-hop chain, and LeadService's card shares no words with *"what depends
   on Score__c?"* Pure vector doesn't return it at any cut-off; the graph
   walk does. That's `retrieve-01`, and the `vector-only-retrieval` mutation
   breaks it. No flow or field counts changed and no expected answer
   changed. I rewrote graph-01's guard text and added graph-04 for the real
   multi-hop impact.

2. **Embed cards, not XML and not summaries.** Raw Flow XML is mostly
   boilerplate, so similarity between two Flows mostly measures how alike
   their tags are. LLM summaries read better, but retrieval would then depend
   on an API key, and results would shift every time a summary was
   regenerated. A card is a few sentences rendered from the catalog and graph
   by code. It's free, the same every run, and every claim on it traces back
   to an edge. It also translates codes into the words people ask with:
   `status=Draft` becomes "not active, so it does not run". One rule I cared
   about: an Apex class card never says "nothing calls this", because the
   parser doesn't see Apex-to-Apex calls. (LeadTrigger *does* call
   LeadService.) A card that states an absence the parser can't see puts a
   false fact straight into the context.

3. **The embedder is lexical, and I shouldn't dress that up.** TF-IDF matches
   words. The "semantic" cases (`retrieve-03`, `retrieve-04`) really pass
   because the question shares words with the card: "screen", "case",
   "draft". Ask "which flows are switched off?" and Retired_Cleanup doesn't
   make the top six. A neural model would do better at genuine paraphrase. I picked TF-IDF for
   reasons that matter here: CI downloads nothing, rankings are deterministic
   enough to assert on in tier 1, and the retriever only sees an interface,
   so `--embedder st` swaps in a sentence-transformer without touching
   fusion. The small fixture also flatters pure vector. With "Lead.Score__c"
   in the question, LeadService still ranks 6th of 11 on the word "lead"
   alone. In a real org, with hundreds of cards saying "Lead", that match
   would be worth nothing. So the bare "Score__c" wording is the one that
   shows the gap cleanly.

4. **RRF, because the scores aren't comparable.** A hop count and a cosine
   similarity have no common unit, and any `0.7 * sim + 0.3 / hops` has
   weights I'd be making up. Reciprocal Rank Fusion only looks at ranks.
   What I didn't expect was its cost showing up in the mutation table.
   `drop-apex-references` breaks `retrieve-05`: without its `triggers_on`
   edge, LeadTrigger is still the #1 vector hit for "what runs when a Lead is
   updated?", yet it drops out of the top 3. RRF ranks anything *both* paths
   found above anything only one path found. On a small catalog nearly
   everything is in both lists, so being found by one path alone is a big
   handicap. Artifacts named in the question are pinned first, outside RRF.
   Otherwise, consensus wins.

5. **Object nodes are hubs, and hubs make graph walks useless.** Nearly
   everything reads or writes Lead. Walk two hops through `object:Lead` and
   every Lead artifact is "related" to every other. So objects are expanded
   only when the question names them. Otherwise the walk can reach them but
   not pass through them. Within a hop count, dependents (what breaks) rank
   ahead of dependencies (what it uses), which rank ahead of mixed paths.

The `graph-only-retrieval` mutation exists because an honest case could catch
it: any question that describes behaviour without naming an artifact leaves
the graph walk nothing to start from. What I haven't measured is retrieval
quality on a real org. Eleven fixture artifacts prove each path contributes.
They don't tell me how often either path is right on four thousand artifacts.

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
