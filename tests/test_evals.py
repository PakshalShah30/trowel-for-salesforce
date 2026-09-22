"""The eval suite, run as tests.

Tier 1 and the mutation harness both run here, so `pytest` alone is the whole
CI gate for the free half. Tier 2 costs money and needs a key, so it is a
separate opt-in command rather than something that silently fails a PR from a
fork.
"""

from __future__ import annotations

import pytest

from evals import mutations as mutations_mod, tier1
from evals.cases import load


@pytest.fixture(scope="module")
def cases():
    return load()


@pytest.fixture(scope="module")
def world():
    return tier1.build_world()


def test_golden_dataset_loads(cases):
    """Validation happens at load time. A malformed case is worse than a
    missing one: it sits in CI looking like coverage while asserting nothing."""
    assert cases
    assert any(c.tier == 1 for c in cases)
    assert any(c.tier == 2 for c in cases)


def test_tier1_all_pass(cases, world):
    artifacts, graph = world
    failures = [r for r in tier1.run(cases, artifacts, graph) if not r.passed]
    assert not failures, "\n".join(
        f"{r.case_id}: expected {r.expected}, got {r.actual} ({r.detail})"
        for r in failures
    )


@pytest.mark.parametrize(
    "mutation", mutations_mod.MUTATIONS, ids=lambda m: m.name
)
def test_mutation_is_caught(cases, mutation):
    """Each known-bad change must break at least one eval case.

    A surviving mutation is not a passing build — it names the exact hole in
    the golden dataset, and the fix is a new case rather than a shrug.
    """
    with mutation.apply() as (artifacts, graph):
        failures = [r.case_id for r in tier1.run(cases, artifacts, graph) if not r.passed]
    assert failures, (
        f"mutation '{mutation.name}' survived the eval suite.\n"
        f"  the mistake: {mutation.mistake.strip()}\n"
        f"  what ships if it survives: {mutation.consequence}"
    )


def test_mutations_restore_global_state(cases, world):
    """Two mutations monkeypatch module globals. If one leaked, every test
    after it would run against a mutated pipeline and the suite would start
    lying — quietly, and in whichever direction the patch happened to push."""
    artifacts, graph = world
    assert all(r.passed for r in tier1.run(cases, artifacts, graph))


def test_tier2_cases_have_usable_rubrics(cases):
    """A rubric that doesn't anchor a 5 gives a score that drifts between runs
    and can't be compared across cases."""
    for case in (c for c in cases if c.tier == 2):
        assert "5" in case.rubric, f"{case.id}: rubric has no anchor for a top score"
        assert len(case.rubric) > 120, f"{case.id}: rubric too thin to grade against"
