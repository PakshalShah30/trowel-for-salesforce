"""Tier 1 evals: deterministic assertions on deterministic output.

Every test here has one correct answer that can be checked by counting, which
is exactly the boundary drawn in detectors.py — facts get exact assertions,
prose gets a judge (Week 5). Nothing in this file calls an LLM, so it runs in
CI on every push, for free, in under a second.

The fixture tree is designed so each Flow disproves a different naive
implementation. If a test here fails, it names the shortcut that was taken.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from archaeologist import catalog as catalog_mod
from archaeologist import detectors, graph as graph_mod, parse
from archaeologist.models import Edge, Kind

FIXTURES = Path(__file__).parent.parent / "fixtures" / "dig-site"


@pytest.fixture(scope="module")
def parsed():
    return parse.parse_tree(FIXTURES)


@pytest.fixture(scope="module")
def built(parsed):
    artifacts, references = parsed
    return artifacts, graph_mod.build(artifacts, references)


# ---------------------------------------------------------------- parsing

def test_all_flows_parsed(parsed):
    artifacts, _ = parsed
    flows = {a.name for a in artifacts if a.kind is Kind.FLOW}
    assert flows == {
        "Lead_Assignment", "Shared_Utility", "Orphan_Notifier",
        "Apex_Invoked_Flow", "Retired_Cleanup", "Case_Intake",
    }


def test_record_triggered_flow_binds_to_its_object(parsed):
    artifacts, _ = parsed
    flow = next(a for a in artifacts if a.name == "Lead_Assignment")
    assert flow.attrs["trigger_type"] == "RecordAfterSave"
    assert flow.attrs["trigger_object"] == "Lead"


def test_autolaunched_flow_has_no_trigger_type(parsed):
    """The distinction TRW001 depends on: both carry processType
    AutoLaunchedFlow, only one carries a triggerType."""
    artifacts, _ = parsed
    flow = next(a for a in artifacts if a.name == "Shared_Utility")
    assert flow.subtype == "AutoLaunchedFlow"
    assert flow.attrs["trigger_type"] is None


def test_subflow_reference_captured(parsed):
    _, references = parsed
    assert any(
        r.source_id == "flow:Lead_Assignment"
        and r.target_id == "flow:Shared_Utility"
        and r.edge is Edge.INVOKES
        for r in references
    )


def test_apex_flow_invocation_captured(parsed):
    _, references = parsed
    assert any(
        r.source_id == "apex_class:LeadService"
        and r.target_id == "flow:Apex_Invoked_Flow"
        and r.edge is Edge.INVOKES
        for r in references
    )


def test_commented_out_apex_is_not_a_reference(parsed):
    """LeadService.cls mentions Orphan_Notifier inside a comment block.

    If this fails, the comment stripper broke and TRW001 will silently stop
    reporting a genuinely dead Flow — a false negative, which is worse than a
    false positive because nothing surfaces to investigate.
    """
    _, references = parsed
    assert not any(r.target_id == "flow:Orphan_Notifier" for r in references)


def test_trigger_binds_to_object(parsed):
    _, references = parsed
    assert any(
        r.source_id == "apex_trigger:LeadTrigger"
        and r.target_id == "object:Lead"
        and r.edge is Edge.TRIGGERS_ON
        for r in references
    )


def test_field_write_captured(parsed):
    _, references = parsed
    assert any(
        r.source_id == "flow:Lead_Assignment"
        and r.target_id == "field:Lead.Score__c"
        and r.edge is Edge.WRITES
        for r in references
    )


def test_no_dangling_edges(built):
    """Every reference target exists as a node. A dangling edge would
    under-count inbound degree and make live artifacts look dead."""
    artifacts, graph = built
    ids = {a.id for a in artifacts}
    for source, target in graph.edges():
        assert source in ids and target in ids


# ---------------------------------------------------------------- graph

def test_impact_is_transitive(built):
    """Score__c is written by Lead_Assignment, which calls Shared_Utility,
    which is reached from the trigger chain. One join would find the first
    of those; the point of the graph is the rest."""
    _, graph = built
    affected = graph_mod.impact(graph, "field:Lead.Score__c")
    assert "flow:Lead_Assignment" in affected
    assert "flow:Shared_Utility" in affected


def test_impact_of_unknown_node_is_empty(built):
    _, graph = built
    assert graph_mod.impact(graph, "field:Lead.Does_Not_Exist__c") == []


# ---------------------------------------------------------------- detectors

def test_dead_automation_finds_exactly_the_orphan(built):
    artifacts, graph = built
    findings = detectors.dead_automation(artifacts, graph)
    assert [f.artifact_id for f in findings] == ["flow:Orphan_Notifier"]


@pytest.mark.parametrize("flow_id,reason", [
    ("flow:Lead_Assignment", "record-triggered: the platform invokes it"),
    ("flow:Shared_Utility", "called as a subflow"),
    ("flow:Apex_Invoked_Flow", "called from Apex"),
    ("flow:Retired_Cleanup", "Draft, not Active"),
    ("flow:Case_Intake", "screen flow: launched outside retrieved metadata"),
])
def test_dead_automation_exclusions(built, flow_id, reason):
    artifacts, graph = built
    flagged = {f.artifact_id for f in detectors.dead_automation(artifacts, graph)}
    assert flow_id not in flagged, f"wrongly flagged — {reason}"


def test_unreferenced_field_finds_exactly_the_legacy_field(built):
    artifacts, graph = built
    findings = detectors.unreferenced_custom_field(artifacts, graph)
    assert [f.artifact_id for f in findings] == ["field:Lead.Legacy_Code__c"]


def test_unreferenced_field_is_info_severity(built):
    """Deliberate downgrade: reports and layouts are out of scope, so this is
    a shortlist for review, not a verdict."""
    artifacts, graph = built
    findings = detectors.unreferenced_custom_field(artifacts, graph)
    assert all(f.severity == "info" for f in findings)


def test_findings_sorted_by_severity(built):
    artifacts, graph = built
    findings = detectors.run_all(artifacts, graph)
    order = {"high": 0, "medium": 1, "info": 2}
    assert [order[f.severity] for f in findings] == sorted(order[f.severity] for f in findings)


# ---------------------------------------------------------------- catalog

def test_catalog_roundtrip(tmp_path, parsed):
    artifacts, references = parsed
    conn = catalog_mod.connect(tmp_path / "t.db")
    catalog_mod.write(conn, artifacts, references)
    assert len(catalog_mod.read_artifacts(conn)) == len(artifacts)
    assert len(catalog_mod.read_references(conn)) == len(set(references))


def test_catalog_write_is_a_replace_not_a_merge(tmp_path, parsed):
    """An excavation is a snapshot. Merging would leave deleted metadata in
    the catalog looking alive."""
    artifacts, references = parsed
    conn = catalog_mod.connect(tmp_path / "t.db")
    catalog_mod.write(conn, artifacts, references)
    catalog_mod.write(conn, artifacts[:2], [])
    assert len(catalog_mod.read_artifacts(conn)) == 2
    assert catalog_mod.read_references(conn) == []


def test_detectors_survive_the_roundtrip(tmp_path, parsed):
    """Findings must be identical whether computed in memory or after a
    catalog write and read. If they diverge, the catalog is lossy."""
    artifacts, references = parsed
    direct = detectors.run_all(artifacts, graph_mod.build(artifacts, references))

    conn = catalog_mod.connect(tmp_path / "t.db")
    catalog_mod.write(conn, artifacts, references)
    reloaded_artifacts = catalog_mod.read_artifacts(conn)
    reloaded = detectors.run_all(
        reloaded_artifacts,
        graph_mod.build(reloaded_artifacts, catalog_mod.read_references(conn)),
    )
    assert [f.artifact_id for f in direct] == [f.artifact_id for f in reloaded]
