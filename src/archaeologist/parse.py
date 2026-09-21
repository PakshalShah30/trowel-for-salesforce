"""Week 3: turn a retrieved metadata tree into artifacts and references.

Scope decision — what this parser deliberately does NOT do
----------------------------------------------------------
It does not extract field-level writes from Apex. Regex over Apex source can
tell you a string like ``lead.Status`` appears; it cannot tell you whether that
line executes, whether ``lead`` is a Lead, or whether the assignment is inside
dead code. A field-conflict finding built on that is a false-positive generator,
and a tool that cries wolf gets uninstalled.

Getting it right needs the Tooling API's ``SymbolTable``, which returns a
compiled view of each class. That is a later week. Until then Apex contributes
two things the regex *can* establish reliably — which Flows it invokes by name,
and which objects it queries — and claims nothing more.

This is the general posture: parse what the format states outright, and leave
inference to a layer that can be evaluated.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import Artifact, Edge, Kind, Reference

# Every Salesforce metadata file carries this namespace on every element.
_NS_RE = re.compile(r"^\{.*?\}")

# Flow elements that perform a database operation and name an <object>.
_RECORD_OPS = {"recordCreates", "recordUpdates", "recordLookups", "recordDeletes"}


def _tag(element: ET.Element) -> str:
    return _NS_RE.sub("", element.tag)


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _tag(child) == name:
            return (child.text or "").strip() or None
    return None


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in element if _tag(c) == name]


# --------------------------------------------------------------------------
# Flow
# --------------------------------------------------------------------------

def parse_flow(path: Path) -> tuple[Artifact, list[Reference]]:
    root = ET.parse(path).getroot()
    name = path.name.replace(".flow-meta.xml", "").replace(".flow", "")
    artifact_id = Artifact.make_id(Kind.FLOW, name)

    status = _child_text(root, "status")
    process_type = _child_text(root, "processType")

    trigger_type = None
    trigger_object = None
    record_trigger_type = None
    for start in _children(root, "start"):
        trigger_type = _child_text(start, "triggerType")
        trigger_object = _child_text(start, "object")
        record_trigger_type = _child_text(start, "recordTriggerType")

    refs: list[Reference] = []

    # Record-triggered Flows bind to an object. This is what makes them
    # reachable without anyone naming them, and it's why they can never be
    # called dead on an inbound-reference count.
    if trigger_type and trigger_object:
        refs.append(Reference(
            artifact_id,
            Artifact.make_id(Kind.OBJECT, trigger_object),
            Edge.TRIGGERS_ON,
            detail=f"{trigger_type} / {record_trigger_type or 'n/a'}",
        ))

    for element in root.iter():
        tag = _tag(element)

        # Subflow elements name another Flow outright.
        if tag == "subflows":
            target = _child_text(element, "flowName")
            if target:
                refs.append(Reference(
                    artifact_id, Artifact.make_id(Kind.FLOW, target),
                    Edge.INVOKES, detail="subflow",
                ))

        # An actionCall of type "flow" is the other way to call one.
        elif tag == "actionCalls":
            if (_child_text(element, "actionType") or "").lower() == "flow":
                target = _child_text(element, "actionName")
                if target:
                    refs.append(Reference(
                        artifact_id, Artifact.make_id(Kind.FLOW, target),
                        Edge.INVOKES, detail="actionCall",
                    ))

        elif tag in _RECORD_OPS:
            obj = _child_text(element, "object") or trigger_object
            if not obj:
                continue
            writes = tag in {"recordCreates", "recordUpdates"}
            refs.append(Reference(
                artifact_id, Artifact.make_id(Kind.OBJECT, obj),
                Edge.WRITES if writes else Edge.READS, detail=tag,
            ))
            for assignment in _children(element, "inputAssignments"):
                field_name = _child_text(assignment, "field")
                if field_name:
                    refs.append(Reference(
                        artifact_id,
                        Artifact.make_id(Kind.FIELD, f"{obj}.{field_name}"),
                        Edge.WRITES, detail=tag,
                    ))
            for filt in _children(element, "filters"):
                field_name = _child_text(filt, "field")
                if field_name:
                    refs.append(Reference(
                        artifact_id,
                        Artifact.make_id(Kind.FIELD, f"{obj}.{field_name}"),
                        Edge.READS, detail=f"{tag} filter",
                    ))

    artifact = Artifact(
        id=artifact_id, kind=Kind.FLOW, name=name, status=status,
        subtype=process_type, path=str(path),
        attrs={
            "trigger_type": trigger_type,
            "trigger_object": trigger_object,
            "record_trigger_type": record_trigger_type,
        },
    )
    return artifact, refs


# --------------------------------------------------------------------------
# Apex
# --------------------------------------------------------------------------

# Flow.Interview.My_Flow  /  Flow.Interview.namespace.My_Flow
_FLOW_INTERVIEW_RE = re.compile(r"Flow\.Interview\.(?:\w+\.)?(\w+)")
_SOQL_FROM_RE = re.compile(r"\bFROM\s+(\w+)", re.IGNORECASE)
_TRIGGER_DECL_RE = re.compile(
    r"\btrigger\s+(\w+)\s+on\s+(\w+)\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL
)
# Block comments and line comments, so commented-out code doesn't count as a reference.
_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def _strip_comments(source: str) -> str:
    return _COMMENT_RE.sub(" ", source)


def _apex_refs(artifact_id: str, source: str) -> list[Reference]:
    refs: list[Reference] = []
    seen: set[tuple[str, str]] = set()
    for flow_name in _FLOW_INTERVIEW_RE.findall(source):
        key = ("invokes", flow_name)
        if key in seen:
            continue
        seen.add(key)
        refs.append(Reference(
            artifact_id, Artifact.make_id(Kind.FLOW, flow_name),
            Edge.INVOKES, detail="Flow.Interview",
        ))
    for obj in _SOQL_FROM_RE.findall(source):
        key = ("reads", obj)
        if key in seen:
            continue
        seen.add(key)
        refs.append(Reference(
            artifact_id, Artifact.make_id(Kind.OBJECT, obj),
            Edge.READS, detail="SOQL",
        ))
    return refs


def parse_apex_class(path: Path) -> tuple[Artifact, list[Reference]]:
    name = path.stem
    artifact_id = Artifact.make_id(Kind.APEX_CLASS, name)
    source = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    artifact = Artifact(id=artifact_id, kind=Kind.APEX_CLASS, name=name, path=str(path))
    return artifact, _apex_refs(artifact_id, source)


def parse_apex_trigger(path: Path) -> tuple[Artifact, list[Reference]]:
    name = path.stem
    artifact_id = Artifact.make_id(Kind.APEX_TRIGGER, name)
    source = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))

    obj = None
    events = None
    match = _TRIGGER_DECL_RE.search(source)
    if match:
        obj = match.group(2)
        events = " ".join(match.group(3).split())

    refs = _apex_refs(artifact_id, source)
    if obj:
        refs.append(Reference(
            artifact_id, Artifact.make_id(Kind.OBJECT, obj),
            Edge.TRIGGERS_ON, detail=events,
        ))

    artifact = Artifact(
        id=artifact_id, kind=Kind.APEX_TRIGGER, name=name,
        subtype=events, path=str(path), attrs={"trigger_object": obj},
    )
    return artifact, refs


# --------------------------------------------------------------------------
# Objects and fields
# --------------------------------------------------------------------------

def parse_field(path: Path) -> tuple[Artifact, list[Reference]] | None:
    """objects/Lead/fields/Score__c.field-meta.xml → field:Lead.Score__c"""
    parts = path.parts
    if "objects" not in parts:
        return None
    obj = parts[parts.index("objects") + 1]
    field_name = path.name.replace(".field-meta.xml", "")
    artifact_id = Artifact.make_id(Kind.FIELD, f"{obj}.{field_name}")

    field_type = None
    try:
        field_type = _child_text(ET.parse(path).getroot(), "type")
    except ET.ParseError:
        pass

    artifact = Artifact(
        id=artifact_id, kind=Kind.FIELD, name=f"{obj}.{field_name}",
        subtype=field_type, path=str(path),
        attrs={"object": obj, "custom": field_name.endswith("__c")},
    )
    # The object owns the field, not the reverse — so no edge is emitted here.
    # Ownership is an attribute; edges are reserved for *usage*, which is the
    # only thing a dead-code question cares about.
    return artifact, []


def parse_object(path: Path) -> tuple[Artifact, list[Reference]]:
    name = path.name.replace(".object-meta.xml", "")
    return Artifact(
        id=Artifact.make_id(Kind.OBJECT, name), kind=Kind.OBJECT,
        name=name, path=str(path),
    ), []


# --------------------------------------------------------------------------
# Tree walk
# --------------------------------------------------------------------------

def parse_tree(root: Path) -> tuple[list[Artifact], list[Reference]]:
    """Walk a retrieved metadata directory and return everything found.

    Objects referenced but never retrieved (standard objects, usually) are
    synthesised as stub artifacts so no edge dangles. A graph with dangling
    edges silently under-reports inbound degree, which would make live things
    look dead — the exact failure this tool must not have.
    """
    artifacts: list[Artifact] = []
    references: list[Reference] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        result: tuple[Artifact, list[Reference]] | None = None

        if name.endswith((".flow-meta.xml", ".flow")):
            result = parse_flow(path)
        elif name.endswith(".cls"):
            result = parse_apex_class(path)
        elif name.endswith(".trigger"):
            result = parse_apex_trigger(path)
        elif name.endswith(".field-meta.xml"):
            result = parse_field(path)
        elif name.endswith(".object-meta.xml"):
            result = parse_object(path)

        if result:
            artifact, refs = result
            artifacts.append(artifact)
            references.extend(refs)

    known = {a.id for a in artifacts}
    for ref in references:
        if ref.target_id in known:
            continue
        kind_value, _, target_name = ref.target_id.partition(":")
        artifacts.append(Artifact(
            id=ref.target_id, kind=Kind(kind_value), name=target_name,
            attrs={"synthesised": True},
        ))
        known.add(ref.target_id)

    return artifacts, references
