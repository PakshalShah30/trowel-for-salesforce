"""Week 3: the dependency graph.

Why a graph and not SQL joins (FRAMEWORK §4)
---------------------------------------------
Both can answer "what directly references Lead.Score__c" — that's one join.

Neither question an architect actually asks is one hop deep. "What breaks if I
delete this field?" is: the Flow that writes it, the Flow that calls *that*
Flow, the Apex that launches that one, the trigger the Apex sits behind. In SQL
that is a recursive CTE whose depth you must guess in advance and whose cycles
you must handle yourself. In a graph it is ``nx.descendants``, and cycles are
already someone else's solved problem.

Impact analysis is the whole product. The data structure should make the
product's central question trivial, and push the awkwardness into the questions
that are merely convenient — which is exactly what the SQLite table is for.
"""

from __future__ import annotations

import networkx as nx

from .models import Artifact, Reference


def build(artifacts: list[Artifact], references: list[Reference]) -> nx.MultiDiGraph:
    """Build the graph. MultiDiGraph, because one Flow can both read and write
    the same field and collapsing those into one edge would lose the distinction
    that conflict detection later depends on."""
    graph = nx.MultiDiGraph()
    for artifact in artifacts:
        graph.add_node(
            artifact.id, kind=artifact.kind.value, name=artifact.name,
            status=artifact.status, subtype=artifact.subtype, **artifact.attrs,
        )
    for ref in references:
        # Both endpoints are guaranteed present: parse_tree synthesises stubs
        # for anything referenced but not retrieved.
        graph.add_edge(ref.source_id, ref.target_id, key=ref.edge.value,
                       edge=ref.edge.value, detail=ref.detail)
    return graph


def inbound(graph: nx.MultiDiGraph, node_id: str, edge: str | None = None) -> list[str]:
    """Who depends on this node. The inbound-degree question, filtered by edge type."""
    if node_id not in graph:
        return []
    return sorted({
        source for source, _, data in graph.in_edges(node_id, data=True)
        if edge is None or data.get("edge") == edge
    })


def outbound(graph: nx.MultiDiGraph, node_id: str, edge: str | None = None) -> list[str]:
    if node_id not in graph:
        return []
    return sorted({
        target for _, target, data in graph.out_edges(node_id, data=True)
        if edge is None or data.get("edge") == edge
    })


def impact(graph: nx.MultiDiGraph, node_id: str) -> list[str]:
    """Everything transitively upstream of this node — the blast radius of deleting it.

    Reversed, because edges point actor → acted-upon: the things at risk are the
    ones that *reach* this node, not the ones it reaches.
    """
    if node_id not in graph:
        return []
    return sorted(nx.descendants(graph.reverse(copy=False), node_id))


def stats(graph: nx.MultiDiGraph) -> dict[str, int]:
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "isolated": len(list(nx.isolates(graph))),
    }
