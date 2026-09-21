"""Week 3: the vocabulary everything else speaks.

An org is modelled as a directed graph of *artifacts* joined by *references*.
Keeping these as plain dataclasses (rather than, say, ORM rows) means the parser,
the SQLite catalog, the networkx graph, and the detectors can all pass the same
objects around without any of them depending on the others.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    """What a node in the dependency graph *is*."""

    FLOW = "flow"
    APEX_CLASS = "apex_class"
    APEX_TRIGGER = "apex_trigger"
    OBJECT = "object"
    FIELD = "field"


class Edge(str, Enum):
    """What one artifact does to another.

    Direction is always *actor → acted-upon*: a Flow that writes Lead.Status is
    ``flow:X --writes--> field:Lead.Status``. Inbound degree is therefore
    "how many things depend on me", which is what every dead-code question asks.
    """

    INVOKES = "invokes"          # Flow calls subflow; Apex calls Flow.Interview
    WRITES = "writes"            # sets a field value
    READS = "reads"              # queries/filters on a field or object
    TRIGGERS_ON = "triggers_on"  # record-triggered Flow or Apex trigger binds to an object


@dataclass(frozen=True)
class Artifact:
    """One thing that exists in the org.

    ``id`` is a stable, human-readable key (``flow:Lead_Assignment``,
    ``field:Lead.Score__c``) rather than a Salesforce record ID, because IDs
    differ per org and the whole point is to compare orgs and diff over time.
    """

    id: str
    kind: Kind
    name: str
    status: str | None = None     # Active / Draft / Obsolete — Flows only
    subtype: str | None = None    # processType for Flows, event list for triggers
    path: str | None = None       # where it came from, for error messages
    attrs: dict = field(default_factory=dict, compare=False)

    @staticmethod
    def make_id(kind: Kind, name: str) -> str:
        return f"{kind.value}:{name}"


@dataclass(frozen=True)
class Reference:
    """A directed edge, with enough detail to explain itself in a report."""

    source_id: str
    target_id: str
    edge: Edge
    detail: str | None = None


@dataclass(frozen=True)
class Finding:
    """A deterministic result. No LLM produced this.

    ``why`` exists because a finding a reader can't act on is just trivia. It
    carries the production consequence, not the rule restated.
    """

    rule: str
    severity: str            # high | medium | info
    artifact_id: str
    message: str
    why: str
