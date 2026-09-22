"""Who evaluates the evaluator?

A green eval suite proves nothing on its own. A suite of cases that always pass
— because they assert something trivially true, or because the query never
touches the code path they claim to guard — looks exactly like a suite that
works, right up until a real regression sails through it.

So each mutation below is a specific, plausible mistake: a shortcut a developer
might genuinely take, or a regression a refactor might genuinely introduce.
Applying one must make at least one eval case fail. If a mutation survives, the
suite has a hole at precisely that spot, and the fix is a new case rather than
a shrug.

This is mutation testing borrowed from unit-test practice and pointed at the
eval suite. It converts "we have evals" into "our evals catch these five named
failures", which is the difference between a claim and evidence.

Run it:  python -m evals.run --mutations

A note on how these are applied, learned the hard way
------------------------------------------------------
The first version of this file returned a mutated world from a plain function
and restored its patches in a ``finally`` before returning. That silently
neutered every mutation that changes *detector* behaviour rather than parser
output: the patch was gone by the time the detectors ran, so the mutation
tested nothing and reported itself as a surviving hole in the eval suite.

Mutations are therefore context managers, and the evaluation happens inside the
``with`` block. The harness caught a bug in the harness, which is the argument
for building it.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

import networkx as nx

from archaeologist import detectors, graph as graph_mod, parse
from archaeologist.models import Artifact, Edge

from .tier1 import FIXTURES

World = tuple[list[Artifact], nx.MultiDiGraph]


@dataclass(frozen=True)
class Mutation:
    name: str
    mistake: str          # the shortcut, in a developer's own words
    consequence: str      # what goes wrong in production if it ships
    apply: Callable[[], Iterator[World]]


def _baseline() -> World:
    artifacts, references = parse.parse_tree(FIXTURES)
    return artifacts, graph_mod.build(artifacts, references)


@contextmanager
def _drop_apex_references() -> Iterator[World]:
    """"Apex is hard to parse, and Flows are the real target anyway.\""""
    artifacts, references = parse.parse_tree(FIXTURES)
    kept = [r for r in references if not r.source_id.startswith("apex_")]
    yield artifacts, graph_mod.build(artifacts, kept)


@contextmanager
def _ignore_comments() -> Iterator[World]:
    """"Stripping comments is an optimisation; the regex is fine as-is.\""""
    original = parse._strip_comments
    parse._strip_comments = lambda source: source  # type: ignore[assignment]
    try:
        artifacts, references = parse.parse_tree(FIXTURES)
        yield artifacts, graph_mod.build(artifacts, references)
    finally:
        parse._strip_comments = original  # type: ignore[assignment]


@contextmanager
def _processtype_only() -> Iterator[World]:
    """"Record-triggered Flows have their own processType, don't they?\"

    This one patches the detector, not the parser, so the patch has to survive
    until the detectors actually run — hence the context manager.
    """
    original = detectors._is_record_triggered
    detectors._is_record_triggered = lambda artifact: False  # type: ignore[assignment]
    try:
        yield _baseline()
    finally:
        detectors._is_record_triggered = original  # type: ignore[assignment]


@contextmanager
def _collapse_edge_types() -> Iterator[World]:
    """"A DiGraph is simpler than a MultiDiGraph; an edge is an edge.\""""
    artifacts, references = parse.parse_tree(FIXTURES)
    flattened = [
        type(r)(r.source_id, r.target_id, Edge.READS, r.detail) for r in references
    ]
    yield artifacts, graph_mod.build(artifacts, flattened)


@contextmanager
def _direct_dependencies_only() -> Iterator[World]:
    """"Impact analysis is a join: find what references the node.\"

    Modelled by stripping flow-to-flow edges, which is what collapses a
    transitive walk into a single hop.
    """
    artifacts, references = parse.parse_tree(FIXTURES)
    kept = [
        r for r in references
        if not (r.edge is Edge.INVOKES and r.source_id.startswith("flow:"))
    ]
    yield artifacts, graph_mod.build(artifacts, kept)


MUTATIONS = [
    Mutation(
        "drop-apex-references", _drop_apex_references.__doc__ or "",
        "A Flow whose only caller is Apex gets reported dead. Someone "
        "deactivates it and a trigger path breaks in production.",
        _drop_apex_references,
    ),
    Mutation(
        "ignore-comments", _ignore_comments.__doc__ or "",
        "A commented-out Flow.Interview call counts as a live caller, so a "
        "genuinely dead Flow is never reported. A false negative: nothing "
        "surfaces, so nobody investigates.",
        _ignore_comments,
    ),
    Mutation(
        "processtype-only", _processtype_only.__doc__ or "",
        "Every working record-triggered Flow in the org is flagged as dead. "
        "The first run produces hundreds of false positives and the tool is "
        "never opened again.",
        _processtype_only,
    ),
    Mutation(
        "collapse-edge-types", _collapse_edge_types.__doc__ or "",
        "Reads and writes become indistinguishable, so 'what writes this "
        "field' can no longer be answered and conflict detection is impossible.",
        _collapse_edge_types,
    ),
    Mutation(
        "direct-dependencies-only", _direct_dependencies_only.__doc__ or "",
        "Impact analysis reports one hop. The second-order breakage — the Flow "
        "that calls the Flow that writes the field — is invisible, which is "
        "the entire reason anyone runs impact analysis.",
        _direct_dependencies_only,
    ),
]
