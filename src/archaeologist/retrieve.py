"""Week 4: hybrid retrieval. Graph for exact references, vectors for the rest.

Why not pure vector RAG (FRAMEWORK §4)
--------------------------------------
Ask "what depends on Score__c?" and a vector index returns the cards that
*mention* Score__c. That catches the direct readers and writers and nothing
else. ``LeadService`` launches ``Apex_Invoked_Flow``, which filters on the
field, but LeadService's own card never mentions Score__c. It is two hops away
in the dependency graph, shares no word with the question, and only something
that walks edges can find it. The vector answer ("these three Flows") looks
complete and is wrong by exactly the second-order breakage that impact
analysis exists to find. (Eval case ``retrieve-01``; the ``vector-only-retrieval``
mutation breaks it.)

Why not graph-only
------------------
A graph walk needs somewhere to start. "Is there a screen a user fills in to
log a new case?" names nothing in the catalog, so the graph path returns nothing at all. The vector
path over artifact cards (see ``cards.py``) still has something to match.

How the two are combined: Reciprocal Rank Fusion
------------------------------------------------
Each path produces a ranked list. The fused score of an artifact is
``sum(1 / (rrf_k + rank))`` over the lists it appears in, with ``rrf_k = 60``
(the constant from the original RRF paper, Cormack et al. 2009).

RRF is chosen because it uses *ranks only*. The two paths produce scores that
aren't comparable: a hop count and a cosine similarity have no common unit, and
any formula that adds them (``0.7 * sim + 0.3 / hops``) needs weights that are
guesses and that break the moment the embedder changes. RRF needs no
calibration, is a few lines, and is easy to explain in a report. Its behaviour
is also easy to state:

* Something both paths found beats something only one path found.
* Among single-path hits, a graph hit at graph rank *r* is outranked only by
  graph hits above it and by vector-only hits ranked strictly above *r* (ties
  go to the graph hit). A long tail of weak vector matches can't bury it.

The first property cuts both ways, and this is the honest cost of RRF. On a
small catalog where nearly every card shares a word with the question, nearly
everything is in both lists. A hit only one path found, even at rank 1 there,
then drops below all of them. The eval suite shows it: when the Apex trigger
loses its ``triggers_on`` edge, LeadTrigger is still the top vector hit for
"what runs when a Lead is updated?" and still falls out of the top 3.
``vector_depth`` caps the vector list so that at org scale "in both lists"
means something.

One rule sits outside RRF: **artifacts named in the question are pinned to the
top**, in the order they were named. If you ask about ``Orphan_Notifier``, a
retriever that returns it fourth is broken, whatever the arithmetic says.

How the graph walk ranks
------------------------
Breadth-first from each named artifact, up to ``hops`` edges, following edges
in both directions. Within a hop count, paths are ordered by what they mean:

1. **dependents**: every edge walked against its direction, i.e. things that
   use the named artifact (what breaks if you change it)
2. **dependencies**: every edge walked with its direction (what it uses)
3. **related**: mixed direction, e.g. another Flow that reads the same field

Object nodes are hubs: nearly everything reads or writes Lead. Walking
*through* one connects every Lead artifact to every other in two hops, which is
noise rather than structure. So an object is expanded only when the question
names it; otherwise it is a dead end the walk can reach but not pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import networkx as nx

from . import cards as cards_mod
from . import embed as embed_mod
from .models import Artifact, Edge, Kind

RRF_K = 60
DEFAULT_HOPS = 2
# How many vector hits enter fusion. Past this, similarity is mostly a shared
# common word, and admitting it would let everything count as "in both lists".
VECTOR_DEPTH = 50

# Tie-break within a hop count. What fires on a thing matters more to "what
# happens when..." than who happens to query it.
_EDGE_PRIORITY = {
    Edge.TRIGGERS_ON.value: 0,
    Edge.WRITES.value: 1,
    Edge.INVOKES.value: 2,
    Edge.READS.value: 3,
}
_DIRECTION_ORDER = {"dependent": 0, "dependency": 1, "related": 2}


@dataclass(frozen=True)
class Hit:
    artifact_id: str
    score: float                       # fused RRF score (named hits are pinned regardless)
    sources: tuple[str, ...]           # ("graph",), ("vector",), or both
    reasons: tuple[str, ...]           # human-readable provenance, one per source
    card: str
    graph_rank: int | None = None
    vector_rank: int | None = None
    similarity: float | None = None
    named: bool = False


@dataclass
class _GraphHit:
    node: str
    hops: int
    direction: str                     # dependent | dependency | related | named
    steps: list[tuple[str, str, str]] = field(default_factory=list)  # (src, edge, dst)
    seed: str = ""

    def sort_key(self) -> tuple:
        first_edge = _EDGE_PRIORITY.get(self.steps[0][1], 9) if self.steps else -1
        return (self.hops, _DIRECTION_ORDER.get(self.direction, -1), first_edge, self.node)

    def reason(self) -> str:
        if not self.steps:
            return "named in question"
        chain = "; ".join(f"{s} {e} {d}" for s, e, d in self.steps)
        hop_word = "hop" if self.hops == 1 else "hops"
        return f"{self.hops} {hop_word} from {self.seed} ({self.direction}): {chain}"


# --------------------------------------------------------------------------
# Reference detection
# --------------------------------------------------------------------------

def _surface_forms(artifact: Artifact) -> set[str]:
    """Every way a question might name this artifact."""
    forms = {artifact.id, artifact.name}
    if "_" in artifact.name and artifact.kind is not Kind.FIELD:
        forms.add(artifact.name.replace("_", " "))      # "Lead Assignment"
    if artifact.kind is Kind.FIELD and "." in artifact.name:
        forms.add(artifact.name.split(".", 1)[1])       # "Score__c"
    if artifact.kind is Kind.OBJECT:
        forms.add(artifact.name + "s")                  # "Leads"
    return {f for f in forms if len(f) >= 3}


def detect_references(question: str, artifacts: list[Artifact]) -> list[str]:
    """Artifact ids named in the question, in order of first mention.

    Case-insensitive, whole-token, longest match wins: ``Lead.Score__c`` names
    the field and does not *also* name the Lead object, and ``LeadService``
    does not name Lead at all. A bare field name (``Score__c``) names every
    field with that API name, since the question didn't say which object.
    """
    by_form: dict[str, set[str]] = {}
    for artifact in artifacts:
        for form in _surface_forms(artifact):
            by_form.setdefault(form.lower(), set()).add(artifact.id)

    lowered = question.lower()
    matches: list[tuple[int, int, str]] = []
    for form in sorted(by_form, key=len, reverse=True):
        pattern = re.compile(r"(?<![\w:])" + re.escape(form) + r"(?![\w])")
        for m in pattern.finditer(lowered):
            matches.append((m.start(), m.end(), form))

    # Longest first, then leftmost; drop anything overlapping a kept span.
    matches.sort(key=lambda t: (-(t[1] - t[0]), t[0]))
    kept: list[tuple[int, int, str]] = []
    for start, end, form in matches:
        if any(start < k_end and k_start < end for k_start, k_end, _ in kept):
            continue
        kept.append((start, end, form))

    ordered: list[str] = []
    for _, _, form in sorted(kept):
        for artifact_id in sorted(by_form[form]):
            if artifact_id not in ordered:
                ordered.append(artifact_id)
    return ordered


# --------------------------------------------------------------------------
# The two paths
# --------------------------------------------------------------------------

def _graph_candidates(graph: nx.MultiDiGraph, seeds: list[str],
                      hops: int = DEFAULT_HOPS) -> list[_GraphHit]:
    """Named artifacts, then everything within ``hops`` edges, ranked."""
    best: dict[str, _GraphHit] = {}
    for seed in seeds:
        if seed not in graph:
            continue
        best.setdefault(seed, _GraphHit(seed, 0, "named", seed=seed))

    for seed in seeds:
        if seed not in graph:
            continue
        frontier = [_GraphHit(seed, 0, "named", seed=seed)]
        for depth in range(1, hops + 1):
            nxt: dict[str, _GraphHit] = {}
            for here in frontier:
                node = here.node
                is_object = graph.nodes[node].get("kind") == Kind.OBJECT.value
                if is_object and node != seed:
                    continue  # hubs are reachable, not traversable
                steps_out = [
                    (dst, (node, d["edge"], dst), "dependency")
                    for _, dst, d in graph.out_edges(node, data=True)
                ]
                steps_in = [
                    (src, (src, d["edge"], node), "dependent")
                    for src, _, d in graph.in_edges(node, data=True)
                ]
                for other, step, direction in steps_in + steps_out:
                    if other == seed:
                        continue
                    if here.direction in ("named", direction):
                        combined = direction
                    else:
                        combined = "related"
                    candidate = _GraphHit(other, depth, combined,
                                          here.steps + [step], seed=seed)
                    current = nxt.get(other)
                    if current is None or candidate.sort_key() < current.sort_key():
                        nxt[other] = candidate
            frontier = []
            for node, candidate in sorted(nxt.items()):
                current = best.get(node)
                if current is None or candidate.sort_key() < current.sort_key():
                    best[node] = candidate
                    frontier.append(candidate)

    named = [best[s] for s in dict.fromkeys(seeds) if s in best]
    rest = sorted((h for h in best.values() if h.hops > 0), key=lambda h: h.sort_key())
    return named + rest


def _vector_candidates(question: str, card_ids: list[str], vectors: list,
                       embedder: embed_mod.Embedder,
                       depth: int = VECTOR_DEPTH) -> list[tuple[str, float]]:
    query = embedder.embed_query(question)
    scored = [
        (card_id, embedder.similarity(query, vec))
        for card_id, vec in zip(card_ids, vectors)
    ]
    scored = [(cid, s) for cid, s in scored if s > 0.0]
    return sorted(scored, key=lambda t: (-t[1], t[0]))[:depth]


# --------------------------------------------------------------------------
# The retriever
# --------------------------------------------------------------------------

class Retriever:
    """Build once per catalog, ask many questions.

    ``use_graph`` and ``use_vector`` exist for ablation: the unit tests use
    them to show what each path contributes. (The mutation harness patches
    ``_graph_candidates`` / ``_vector_candidates`` instead, so it exercises
    the same code path the eval cases call.)
    """

    def __init__(self, artifacts: list[Artifact], graph: nx.MultiDiGraph,
                 embedder: embed_mod.Embedder | None = None, *,
                 hops: int = DEFAULT_HOPS, rrf_k: int = RRF_K,
                 vector_depth: int = VECTOR_DEPTH,
                 use_graph: bool = True, use_vector: bool = True) -> None:
        self.artifacts = artifacts
        self.graph = graph
        self.hops = hops
        self.vector_depth = vector_depth
        self.rrf_k = rrf_k
        self.use_graph = use_graph
        self.use_vector = use_vector
        self.cards = cards_mod.build(artifacts, graph)
        self.embedder = embedder or embed_mod.TfidfEmbedder()
        self._card_ids = list(self.cards)
        texts = [self.cards[i].text for i in self._card_ids]
        self.embedder.fit(texts)
        self._vectors = self.embedder.embed_documents(texts)

    def graph_path(self, question: str) -> list[_GraphHit]:
        seeds = detect_references(question, self.artifacts)
        return _graph_candidates(self.graph, seeds, self.hops)

    def vector_path(self, question: str) -> list[tuple[str, float]]:
        return _vector_candidates(question, self._card_ids, self._vectors, self.embedder,
                                  self.vector_depth)

    def retrieve(self, question: str, k: int = 8) -> list[Hit]:
        graph_hits = self.graph_path(question) if self.use_graph else []
        vector_hits = self.vector_path(question) if self.use_vector else []
        return fuse(graph_hits, vector_hits, self.cards, k=k, rrf_k=self.rrf_k)


def fuse(graph_hits: list[_GraphHit], vector_hits: list[tuple[str, float]],
         cards: dict[str, cards_mod.Card], *, k: int = 8,
         rrf_k: int = RRF_K) -> list[Hit]:
    """Reciprocal Rank Fusion, with named artifacts pinned first."""
    graph_rank = {h.node: i for i, h in enumerate(graph_hits, start=1)}
    graph_by_id = {h.node: h for h in graph_hits}
    vector_rank = {cid: i for i, (cid, _) in enumerate(vector_hits, start=1)}
    similarity = dict(vector_hits)

    scores: dict[str, float] = {}
    for cid, rank in graph_rank.items():
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
    for cid, rank in vector_rank.items():
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)

    def order(cid: str) -> tuple:
        named = cid in graph_by_id and graph_by_id[cid].hops == 0
        return (
            0 if named else 1,
            graph_rank[cid] if named else 0,
            -scores[cid],
            graph_rank.get(cid, 10**9),   # ties go to the structurally exact hit
            vector_rank.get(cid, 10**9),
            cid,
        )

    hits: list[Hit] = []
    for cid in sorted(scores, key=order)[:k]:
        sources: list[str] = []
        reasons: list[str] = []
        if cid in graph_by_id:
            sources.append("graph")
            reasons.append(graph_by_id[cid].reason())
        if cid in vector_rank:
            sources.append("vector")
            reasons.append(f"similarity {similarity[cid]:.2f} (vector rank {vector_rank[cid]})")
        card = cards.get(cid)
        hits.append(Hit(
            artifact_id=cid,
            score=scores[cid],
            sources=tuple(sources),
            reasons=tuple(reasons),
            card=card.text if card else "",
            graph_rank=graph_rank.get(cid),
            vector_rank=vector_rank.get(cid),
            similarity=similarity.get(cid),
            named=cid in graph_by_id and graph_by_id[cid].hops == 0,
        ))
    return hits


def retrieve(artifacts: list[Artifact], graph: nx.MultiDiGraph, question: str,
             k: int = 8, embedder: embed_mod.Embedder | None = None,
             hops: int = DEFAULT_HOPS) -> list[Hit]:
    """One-shot convenience wrapper. Builds a ``Retriever`` and asks once.

    The eval harness calls this, so mutations that patch ``_graph_candidates``
    or ``_vector_candidates`` take effect here.
    """
    return Retriever(artifacts, graph, embedder, hops=hops).retrieve(question, k=k)
