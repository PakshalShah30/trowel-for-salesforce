"""Week 4: artifact cards, the text that gets embedded.

A card is a short plain-English description of one artifact, rendered
deterministically from the catalog and the dependency graph. No model writes
it. Every sentence on a card traces back to an attribute or an edge.

Why cards, and not the raw XML or an LLM summary
------------------------------------------------
**Raw XML is mostly noise.** A Flow file is namespaces, element names,
``apiVersion``, layout coordinates, and the same tag repeated a dozen times.
Embed that and the similarity between two Flows mostly measures how alike
their XML boilerplate is. The words that matter ("runs after a Lead is saved",
"writes Score__c") are either absent or buried.

**An LLM summary makes retrieval depend on an API key and on luck.** The
summariser from Week 2 produces good prose, but the prose changes between runs,
costs money per artifact, and can hallucinate a field that then becomes
retrievable. Retrieval that shifts when the summary is regenerated can't be
held to an exact eval.

**Cards are free, reproducible, and testable.** Same catalog in, same text out,
byte for byte. They also do one useful translation: Salesforce codes become the
words people actually ask with. ``processType=Flow`` becomes "screen flow, a
user launches it"; ``status=Draft`` becomes "not active, it does not run". A
question like "which automations never run?" can then match something.

What a card deliberately does *not* say
---------------------------------------
Only what the graph can establish. The parser does not capture Apex-to-Apex
calls (see ``parse.py``), so an Apex class card never claims "nothing calls
this". It just doesn't list callers. A card that asserts an absence the parser
can't see would feed a false fact straight into the retrieved context.

Future work, not built: when an LLM summary exists for an artifact, append it
to the card as a clearly separated section, so the deterministic part stays
the part the evals check.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .models import Artifact, Edge, Kind


@dataclass(frozen=True)
class Card:
    artifact_id: str
    title: str
    text: str


# Human wording for each kind, used in titles and neighbour lists.
_KIND_WORD = {
    Kind.FLOW: "flow",
    Kind.APEX_CLASS: "Apex class",
    Kind.APEX_TRIGGER: "Apex trigger",
    Kind.OBJECT: "object",
    Kind.FIELD: "field",
}


def _readable(name: str) -> str:
    """``Lead_Assignment`` → ``Lead Assignment``. Flow labels are not parsed,
    so this is the closest the card gets to the name a human would type."""
    return name.replace("__c", "").replace("_", " ").replace(".", " ").strip()


def _node_label(graph: nx.MultiDiGraph, node_id: str) -> str:
    data = graph.nodes[node_id]
    try:
        kind = Kind(data.get("kind"))
    except ValueError:
        return node_id
    return f"{_KIND_WORD[kind]} {data.get('name', node_id)}"


def _neighbours(graph: nx.MultiDiGraph, node_id: str, edge: Edge,
                inbound: bool) -> list[str]:
    edges = graph.in_edges(node_id, data=True) if inbound else graph.out_edges(node_id, data=True)
    ids = {
        (src if inbound else dst)
        for src, dst, data in edges
        if data.get("edge") == edge.value
    }
    return [_node_label(graph, n) for n in sorted(ids)]


def _list(label: str, items: list[str]) -> str | None:
    return f"{label}: {', '.join(items)}." if items else None


def _flow_lines(artifact: Artifact, graph: nx.MultiDiGraph) -> list[str | None]:
    lines: list[str | None] = []
    status = artifact.status or "unknown"
    if status.lower() == "active":
        lines.append("Status: Active.")
    else:
        lines.append(f"Status: {status}. Not active, so it does not run.")

    process_type = artifact.subtype or "unknown"
    trigger_type = artifact.attrs.get("trigger_type")
    trigger_object = artifact.attrs.get("trigger_object")
    record_trigger = artifact.attrs.get("record_trigger_type")

    if trigger_type and trigger_object:
        when = {
            "RecordAfterSave": "after",
            "RecordBeforeSave": "before",
            "RecordBeforeDelete": "before",
        }.get(trigger_type, "on")
        what = {
            "Create": "created",
            "Update": "updated",
            "CreateAndUpdate": "created or updated",
            "Delete": "deleted",
        }.get(record_trigger or "", "changed")
        save = "deleted" if trigger_type == "RecordBeforeDelete" else "saved"
        lines.append(
            f"Record-triggered flow ({process_type}, {trigger_type}): runs automatically "
            f"{when} a {trigger_object} record is {save}, when it is {what}. "
            f"The platform starts it; nothing needs to invoke it by name."
        )
    elif process_type.lower() == "autolaunchedflow":
        lines.append(
            f"Autolaunched flow ({process_type}): runs only when another flow, "
            f"Apex, or an external caller invokes it by name."
        )
    elif process_type.lower() == "flow":
        lines.append(
            "Screen flow (processType Flow): a user launches it from a page, "
            "button, quick action, or URL."
        )
    else:
        lines.append(f"Process type: {process_type}.")

    lines.append(_list("Writes", _neighbours(graph, artifact.id, Edge.WRITES, inbound=False)))
    lines.append(_list("Reads", _neighbours(graph, artifact.id, Edge.READS, inbound=False)))
    lines.append(_list("Invokes", _neighbours(graph, artifact.id, Edge.INVOKES, inbound=False)))

    callers = _neighbours(graph, artifact.id, Edge.INVOKES, inbound=True)
    if callers:
        lines.append(_list("Invoked by", callers))
    elif not trigger_type and process_type.lower() == "autolaunchedflow":
        # Scoped to what was retrieved: Process Builder, platform events and
        # REST callers are outside it (see detectors.dead_automation).
        lines.append("Nothing in the retrieved metadata invokes it.")
    return lines


def _apex_class_lines(artifact: Artifact, graph: nx.MultiDiGraph) -> list[str | None]:
    return [
        _list("Invokes", _neighbours(graph, artifact.id, Edge.INVOKES, inbound=False)),
        _list("Queries (SOQL)", _neighbours(graph, artifact.id, Edge.READS, inbound=False)),
        # No "called by" line: Apex-to-Apex calls are not parsed, so absence
        # of an inbound edge here proves nothing and must not be stated.
    ]


def _apex_trigger_lines(artifact: Artifact, graph: nx.MultiDiGraph) -> list[str | None]:
    obj = artifact.attrs.get("trigger_object")
    events = artifact.subtype
    lines: list[str | None] = []
    if obj:
        lines.append(
            f"Fires on {obj} records"
            + (f" ({events})." if events else ".")
        )
    lines.append(_list("Invokes", _neighbours(graph, artifact.id, Edge.INVOKES, inbound=False)))
    lines.append(_list("Queries (SOQL)", _neighbours(graph, artifact.id, Edge.READS, inbound=False)))
    return lines


def _object_lines(artifact: Artifact, graph: nx.MultiDiGraph,
                  artifacts: list[Artifact]) -> list[str | None]:
    lines: list[str | None] = []
    if artifact.attrs.get("synthesised"):
        lines.append("Referenced but not retrieved (usually a standard object).")
    lines.append(_list("Automation that fires on it",
                       _neighbours(graph, artifact.id, Edge.TRIGGERS_ON, inbound=True)))
    lines.append(_list("Written by", _neighbours(graph, artifact.id, Edge.WRITES, inbound=True)))
    lines.append(_list("Read by", _neighbours(graph, artifact.id, Edge.READS, inbound=True)))
    fields = sorted(
        a.name for a in artifacts
        if a.kind is Kind.FIELD and a.attrs.get("object") == artifact.name
    )
    lines.append(_list("Fields in catalog", fields))
    return lines


def _field_lines(artifact: Artifact, graph: nx.MultiDiGraph) -> list[str | None]:
    obj = artifact.attrs.get("object") or artifact.name.partition(".")[0]
    custom = "Custom field" if artifact.attrs.get("custom") or artifact.name.endswith("__c") \
        else "Standard field"
    kind_bits = f"{custom} on {obj}" + (f", type {artifact.subtype}" if artifact.subtype else "")
    lines: list[str | None] = [kind_bits + "."]
    if artifact.attrs.get("synthesised"):
        lines.append("Referenced but not retrieved.")
    writers = _neighbours(graph, artifact.id, Edge.WRITES, inbound=True)
    readers = _neighbours(graph, artifact.id, Edge.READS, inbound=True)
    lines.append(_list("Written by", writers))
    lines.append(_list("Read by", readers))
    if not writers and not readers:
        lines.append("No reader or writer in the retrieved metadata.")
    return lines


def render(artifact: Artifact, graph: nx.MultiDiGraph,
           artifacts: list[Artifact]) -> Card:
    """One artifact → one card. Pure function of the catalog and graph."""
    title = f"{_KIND_WORD[artifact.kind]} {artifact.name}"
    if artifact.kind is Kind.FLOW:
        body = _flow_lines(artifact, graph)
    elif artifact.kind is Kind.APEX_CLASS:
        body = _apex_class_lines(artifact, graph)
    elif artifact.kind is Kind.APEX_TRIGGER:
        body = _apex_trigger_lines(artifact, graph)
    elif artifact.kind is Kind.OBJECT:
        body = _object_lines(artifact, graph, artifacts)
    else:
        body = _field_lines(artifact, graph)

    readable = _readable(artifact.name)
    header = f"{title[0].upper()}{title[1:]}" + (
        f" ({readable})." if readable != artifact.name else "."
    )
    text = " ".join([header] + [line for line in body if line])
    return Card(artifact_id=artifact.id, title=title, text=text)


def build(artifacts: list[Artifact], graph: nx.MultiDiGraph) -> dict[str, Card]:
    """Every artifact's card, keyed by id, in id order."""
    return {
        a.id: render(a, graph, artifacts)
        for a in sorted(artifacts, key=lambda a: a.id)
    }
