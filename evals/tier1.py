"""Tier 1: facts, checked by counting.

Why facts never reach the judge (FRAMEWORK §6)
-----------------------------------------------
"Which Flows does nothing invoke" has one correct answer, derivable from the
metadata. Handing that to a model to grade adds cost, latency, and a nonzero
error rate to a question that a set comparison answers perfectly.

It also answers the circularity objection people raise about LLM-as-judge. The
objection is real when a model grades another model on a question of fact —
both can be wrong in the same direction, and the score looks fine. It does not
apply here, because the judge is never asked about facts. It is asked whether a
piece of prose is a good explanation, which is a question about writing.

Retrieval (Week 4) is tier 1 too. With the default TF-IDF embedder the
ranking is a deterministic function of the catalog, so "is LeadService in the
top 6 for this question" has one correct answer and gets a set check. With a
neural embedder that would stop being true, which is one reason the default
isn't neural (see ``archaeologist/embed.py``).

The practical payoff: tier 1 needs no API key, so it runs on every pull request
for free, in under a second. Cost is a design constraint on evals. An eval
suite that is expensive to run is an eval suite that gets skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

from archaeologist import detectors, graph as graph_mod, parse
from archaeologist import retrieve as retrieve_mod
from archaeologist.models import Artifact, Kind

from .cases import Case

FIXTURES = Path(__file__).parent.parent / "fixtures" / "dig-site"


@dataclass(frozen=True)
class Result:
    case_id: str
    passed: bool
    expected: Any
    actual: Any
    detail: str = ""


def build_world(fixtures: Path = FIXTURES) -> tuple[list[Artifact], nx.MultiDiGraph]:
    artifacts, references = parse.parse_tree(fixtures)
    return artifacts, graph_mod.build(artifacts, references)


def answer(case: Case, artifacts: list[Artifact], graph: nx.MultiDiGraph) -> Any:
    """Execute one tier-1 query against the world."""
    query = case.query or {}
    op = query["op"]

    if op == "detect":
        rule = query["rule"]
        return sorted(
            f.artifact_id for f in detectors.run_all(artifacts, graph) if f.rule == rule
        )
    if op == "impact":
        return graph_mod.impact(graph, query["node"])
    if op == "inbound":
        return graph_mod.inbound(graph, query["node"], edge=query.get("edge"))
    if op == "outbound":
        return graph_mod.outbound(graph, query["node"], edge=query.get("edge"))
    if op == "retrieve":
        # The case's own question is the retrieval input: it is literally the
        # question a user would type.
        hits = retrieve_mod.retrieve(artifacts, graph, case.question, k=query["k"])
        return [h.artifact_id for h in hits]
    if op == "count":
        kind = Kind(query["kind"])
        return sum(
            1 for a in artifacts
            if a.kind is kind and not a.attrs.get("synthesised")
        )
    raise ValueError(f"unknown op {op!r}")


def check(case: Case, actual: Any) -> Result:
    if case.match == "contains":
        missing = [item for item in case.expected if item not in actual]
        return Result(
            case.id, not missing, case.expected, actual,
            detail=f"missing {missing}" if missing else "",
        )

    expected = sorted(case.expected) if isinstance(case.expected, list) else case.expected
    got = sorted(actual) if isinstance(actual, list) else actual
    if expected == got:
        return Result(case.id, True, expected, got)

    detail = ""
    if isinstance(expected, list) and isinstance(got, list):
        extra = [i for i in got if i not in expected]
        missing = [i for i in expected if i not in got]
        parts = []
        if missing:
            parts.append(f"missing {missing}")
        if extra:
            parts.append(f"unexpected {extra}")
        detail = "; ".join(parts)
    return Result(case.id, False, expected, got, detail)


def run(cases: list[Case], artifacts: list[Artifact],
        graph: nx.MultiDiGraph) -> list[Result]:
    return [
        check(case, answer(case, artifacts, graph))
        for case in cases if case.tier == 1
    ]
