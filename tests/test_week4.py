"""Week 4: cards, the embedder, reference detection, fusion, and `ask`.

These protect the implementation. The behaviour the product promises ("what
depends on Score__c?" must surface LeadService) lives in the golden dataset as
retrieve-* cases, and the mutation harness proves those cases can fail.

Nothing here loads a neural model. The default embedder is pure Python, and
one test checks that the default path never imports sentence-transformers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from archaeologist import cards as cards_mod
from archaeologist import cli, embed, graph as graph_mod, parse
from archaeologist import retrieve as retrieve_mod
from archaeologist.retrieve import Retriever, _GraphHit, detect_references, fuse

FIXTURES = Path(__file__).parent.parent / "fixtures" / "dig-site"


@pytest.fixture(scope="module")
def world():
    artifacts, references = parse.parse_tree(FIXTURES)
    return artifacts, graph_mod.build(artifacts, references)


@pytest.fixture(scope="module")
def cards(world):
    return cards_mod.build(*world)


@pytest.fixture(scope="module")
def retriever(world):
    return Retriever(*world)


# ---------------------------------------------------------------- cards

def test_every_artifact_has_a_card(world, cards):
    artifacts, _ = world
    assert set(cards) == {a.id for a in artifacts}


def test_cards_are_deterministic(world):
    assert cards_mod.build(*world) == cards_mod.build(*world)


def test_record_triggered_flow_card(cards):
    text = cards["flow:Lead_Assignment"].text
    assert "Record-triggered" in text
    assert "after a Lead record is saved" in text
    assert "Lead.Score__c" in text           # what it writes
    assert "Shared_Utility" in text          # what it invokes


def test_card_states_callers(cards):
    assert "Invoked by: Apex class LeadService" in cards["flow:Apex_Invoked_Flow"].text
    assert "Invoked by: flow Lead_Assignment" in cards["flow:Shared_Utility"].text


def test_codes_become_words(cards):
    """The translation that lets a plain-English question match anything."""
    assert "does not run" in cards["flow:Retired_Cleanup"].text
    assert "Screen flow" in cards["flow:Case_Intake"].text


def test_field_card_lists_readers_and_writers(cards):
    text = cards["field:Lead.Score__c"].text
    assert "Written by: flow Lead_Assignment" in text
    assert "flow Apex_Invoked_Flow" in text and "flow Shared_Utility" in text
    assert "No reader or writer" in cards["field:Lead.Legacy_Code__c"].text


def test_apex_class_card_claims_no_absence_of_callers(cards):
    """Apex-to-Apex calls aren't parsed (LeadTrigger does call LeadService),
    so the card must not claim nothing calls it."""
    text = cards["apex_class:LeadService"].text
    assert "Invoked by" not in text
    assert "Nothing" not in text


# ---------------------------------------------------------------- embedder

def test_tokenize_splits_names_and_drops_suffix_noise():
    assert embed.tokenize("Lead.Score__c") == ["lead", "scor"]
    assert embed.tokenize("LeadService") == ["lead", "servic"]
    assert embed.tokenize("Apex_Invoked_Flow") == ["apex", "invok", "flow"]


def test_stemmer_joins_inflections():
    stems = {embed.tokenize(w)[0] for w in ("update", "updated", "updates", "updating")}
    assert len(stems) == 1


def test_embedder_satisfies_protocol():
    assert isinstance(embed.TfidfEmbedder(), embed.Embedder)


def test_embedder_is_deterministic(cards):
    texts = [c.text for c in cards.values()]
    question = "which flows run when a lead is updated?"

    def ranking() -> list[int]:
        e = embed.TfidfEmbedder()
        e.fit(texts)
        docs = e.embed_documents(texts)
        q = e.embed_query(question)
        sims = [e.similarity(q, d) for d in docs]
        return sorted(range(len(texts)), key=lambda i: (-sims[i], i))

    assert ranking() == ranking()


def test_similarity_bounds():
    e = embed.TfidfEmbedder()
    e.fit(["lead score flow", "case intake screen"])
    doc = e.embed_documents(["lead score flow"])[0]
    assert e.similarity(doc, doc) == pytest.approx(1.0)
    assert e.similarity(e.embed_query("zebra"), doc) == 0.0


def test_unknown_embedder_rejected():
    with pytest.raises(ValueError):
        embed.get("nope")


def test_default_path_never_imports_sentence_transformers(world):
    Retriever(*world).retrieve("what depends on Score__c?")
    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules


# ---------------------------------------------------------------- reference detection

@pytest.mark.parametrize("question,expected", [
    ("What depends on Lead.Score__c?", ["field:Lead.Score__c"]),   # not also object:Lead
    ("What depends on Score__c?", ["field:Lead.Score__c"]),
    ("What does LeadService do?", ["apex_class:LeadService"]),      # not object:Lead
    ("Tell me about the lead assignment flow", ["flow:Lead_Assignment"]),
    ("Which automation touches Leads?", ["object:Lead"]),
    ("is flow:Orphan_Notifier dead?", ["flow:Orphan_Notifier"]),
    ("Is there a screen for logging cases?", []),
])
def test_detect_references(world, question, expected):
    artifacts, _ = world
    assert detect_references(question, artifacts) == expected


def test_detect_references_keeps_mention_order(world):
    artifacts, _ = world
    found = detect_references("Does Shared_Utility read Score__c?", artifacts)
    assert found == ["flow:Shared_Utility", "field:Lead.Score__c"]


# ---------------------------------------------------------------- graph walk

def test_graph_walk_finds_two_hop_dependent(world):
    _, graph = world
    hits = {h.node: h for h in retrieve_mod._graph_candidates(graph, ["field:Lead.Score__c"])}
    service = hits["apex_class:LeadService"]
    assert service.hops == 2
    assert service.direction == "dependent"


def test_graph_walk_does_not_pass_through_unnamed_objects(world):
    """Orphan_Notifier's only link to Score__c is via the Lead object hub.
    Walking through hubs would connect everything to everything."""
    _, graph = world
    hits = {h.node for h in retrieve_mod._graph_candidates(graph, ["field:Lead.Score__c"], hops=3)}
    assert "object:Lead" in hits              # reachable
    assert "flow:Orphan_Notifier" not in hits  # but not traversed


def test_named_object_is_expanded(world):
    _, graph = world
    hits = {h.node for h in retrieve_mod._graph_candidates(graph, ["object:Lead"], hops=1)}
    assert {"apex_trigger:LeadTrigger", "flow:Lead_Assignment", "flow:Orphan_Notifier"} <= hits


# ---------------------------------------------------------------- fusion

def _fake_cards(ids):
    return {i: cards_mod.Card(i, i, i) for i in ids}


def test_graph_only_hit_not_buried_by_many_vector_hits():
    graph_hits = [_GraphHit("x:graph_only", 1, "dependent",
                            [("x:graph_only", "reads", "x:seed")], seed="x:seed")]
    vector_hits = [(f"x:vec{i:02d}", 0.9 - i * 0.01) for i in range(50)]
    fused = fuse(graph_hits, vector_hits, _fake_cards(["x:graph_only"] + [v for v, _ in vector_hits]), k=5)
    ids = [h.artifact_id for h in fused]
    # Same RRF score as vector rank 1; the tie goes to the structural hit.
    assert ids[0] == "x:graph_only"


def test_named_artifact_is_pinned_first():
    graph_hits = [_GraphHit("x:named", 0, "named", seed="x:named")]
    vector_hits = [(f"x:vec{i}", 0.9) for i in range(10)] + [("x:named", 0.01)]
    fused = fuse(graph_hits, vector_hits, _fake_cards([]), k=3)
    assert fused[0].artifact_id == "x:named"
    assert fused[0].named


def test_agreement_beats_single_path():
    graph_hits = [
        _GraphHit("x:g1", 1, "dependent", [("x:g1", "reads", "s")], seed="s"),
        _GraphHit("x:both", 1, "dependent", [("x:both", "reads", "s")], seed="s"),
    ]
    vector_hits = [("x:v1", 0.9), ("x:both", 0.5)]
    fused = fuse(graph_hits, vector_hits, _fake_cards([]), k=3)
    assert fused[0].artifact_id == "x:both"
    assert fused[0].sources == ("graph", "vector")


def test_every_result_has_provenance(retriever):
    for question in ("What depends on Score__c?", "What runs when a Lead is updated?",
                     "Is there a screen a user fills in to log a new case?"):
        for hit in retriever.retrieve(question, k=8):
            assert hit.sources, hit
            assert len(hit.reasons) == len(hit.sources)
            for source, reason in zip(hit.sources, hit.reasons):
                if source == "graph":
                    assert reason == "named in question" or " hop" in reason
                else:
                    assert reason.startswith("similarity ")
            assert hit.card


def test_ablation_shows_what_the_graph_adds(world):
    """The checkpoint answer as a unit test: pure vector never returns the
    two-hop dependent, at any k."""
    question = "What depends on Score__c?"
    hybrid = [h.artifact_id for h in Retriever(*world).retrieve(question, k=6)]
    vector_only = [h.artifact_id for h in
                   Retriever(*world, use_graph=False).retrieve(question, k=100)]
    assert "apex_class:LeadService" in hybrid
    assert "apex_class:LeadService" not in vector_only


def test_ablation_shows_what_vectors_add(world):
    question = "Is there a screen a user fills in to log a new case?"
    assert Retriever(*world, use_vector=False).retrieve(question) == []
    top = Retriever(*world).retrieve(question, k=1)
    assert top[0].artifact_id == "flow:Case_Intake"


# ---------------------------------------------------------------- CLI

def test_cli_ask_runs(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    assert cli.main(["--db", db, "catalog", str(FIXTURES)]) == 0
    assert cli.main(["--db", db, "ask", "What depends on Score__c?", "-k", "6", "--cards"]) == 0
    out = capsys.readouterr().out
    assert "apex_class:LeadService" in out
    assert "named in question" in out


def test_cli_ask_on_empty_catalog(tmp_path):
    assert cli.main(["--db", str(tmp_path / "empty.db"), "ask", "anything"]) == 1
