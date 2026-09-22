"""Loading and validating the golden dataset.

Why a JSONL file and not more pytest functions
-----------------------------------------------
The unit tests in ``tests/`` protect the implementation: they know about
``_is_record_triggered`` and would need rewriting if that function were
renamed. The golden dataset protects the *behaviour the product promises* and
knows nothing about the code — every case is a question with an answer.

That separation is why a refactor can legitimately rewrite every unit test and
must not change a single eval case. If a refactor does change eval answers,
either the behaviour regressed or the promise changed, and both deserve a
conversation rather than a quiet green tick.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).parent / "golden" / "cases.jsonl"

_TIER1_OPS = {"detect", "impact", "inbound", "outbound", "count"}


@dataclass(frozen=True)
class Case:
    id: str
    tier: int
    question: str
    # tier 1
    query: dict[str, Any] | None = None
    expected: Any = None
    match: str = "equals"          # equals | contains
    guards: str | None = None      # what this case would catch if it broke
    # tier 2
    target: str | None = None
    rubric: str | None = None
    min_score: int = 4


def load(path: Path | str = GOLDEN) -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(Path(path).read_text().splitlines(), start=1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: {exc}") from exc

        case = Case(**data)
        if case.id in seen:
            raise ValueError(f"{path}:{line_no}: duplicate case id {case.id!r}")
        seen.add(case.id)
        _validate(case, f"{path}:{line_no}")
        cases.append(case)
    return cases


def _validate(case: Case, where: str) -> None:
    """Fail loudly at load time rather than producing a case that can't fail.

    A malformed eval case is the worst possible artifact: it sits in CI looking
    like coverage while asserting nothing.
    """
    if case.tier == 1:
        if not case.query:
            raise ValueError(f"{where}: tier-1 case {case.id!r} has no query")
        op = case.query.get("op")
        if op not in _TIER1_OPS:
            raise ValueError(f"{where}: unknown op {op!r} (expected one of {sorted(_TIER1_OPS)})")
        if case.expected is None:
            raise ValueError(f"{where}: tier-1 case {case.id!r} has no expected value")
        if case.match not in {"equals", "contains"}:
            raise ValueError(f"{where}: bad match mode {case.match!r}")
    elif case.tier == 2:
        if not case.target or not case.rubric:
            raise ValueError(f"{where}: tier-2 case {case.id!r} needs a target and a rubric")
        if not 1 <= case.min_score <= 5:
            raise ValueError(f"{where}: min_score out of range for {case.id!r}")
    else:
        raise ValueError(f"{where}: unknown tier {case.tier}")
