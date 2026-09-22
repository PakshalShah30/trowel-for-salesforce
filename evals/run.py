"""The eval CLI.

    python -m evals.run                 # tier 1 (free, no API key)
    python -m evals.run --tier2         # adds the judged tier (costs money)
    python -m evals.run --mutations     # prove the suite catches known mistakes
    python -m evals.run --json          # machine-readable, for CI artifacts

Exit codes: 0 all passed, 1 a case failed, 2 the suite itself is broken
(malformed cases, or a mutation nothing caught).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import judge as judge_mod, mutations as mutations_mod, tier1
from .cases import load

REPO_ROOT = Path(__file__).parent.parent
console = Console()


def _run_tier1(cases, quiet: bool = False):
    artifacts, graph = tier1.build_world()
    results = tier1.run(cases, artifacts, graph)
    if quiet:
        return results

    table = Table(title="Tier 1 — deterministic", header_style="bold")
    table.add_column(""); table.add_column("Case"); table.add_column("Detail")
    for result in results:
        table.add_row(
            "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]",
            result.case_id,
            result.detail or "",
        )
    console.print(table)
    return results


def _run_mutations(cases) -> bool:
    """Every mutation must break at least one case. Report which."""
    console.print("\n[bold]Mutation testing — does the suite have teeth?[/bold]\n")
    table = Table(header_style="bold")
    table.add_column(""); table.add_column("Mutation")
    table.add_column("Caught by", overflow="fold")

    all_caught = True
    for mutation in mutations_mod.MUTATIONS:
        # Evaluate inside the context: mutations that patch detector behaviour
        # must stay applied until the detectors actually run.
        with mutation.apply() as (artifacts, graph):
            failures = [r.case_id for r in tier1.run(cases, artifacts, graph) if not r.passed]
        caught = bool(failures)
        all_caught &= caught
        table.add_row(
            "[green]caught[/green]" if caught else "[red]SURVIVED[/red]",
            mutation.name,
            ", ".join(failures) if caught else "[red]nothing — the suite has a hole here[/red]",
        )
    console.print(table)

    if not all_caught:
        console.print(
            "\n[red]A mutation survived.[/red] That is a missing eval case, not a "
            "passing build — add a case that fails under it."
        )
    return all_caught


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals")
    parser.add_argument("--tier2", action="store_true", help="run the judged tier (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--mutations", action="store_true", help="verify the suite catches known mistakes")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        cases = load()
    except ValueError as exc:
        console.print(f"[red]Malformed golden dataset:[/red] {exc}")
        return 2

    results = _run_tier1(cases, quiet=args.json)
    failed = [r for r in results if not r.passed]

    judgements = []
    skipped_tier2 = False
    if args.tier2:
        tier2_cases = [c for c in cases if c.tier == 2]
        try:
            judgements = judge_mod.run(tier2_cases, REPO_ROOT)
        except judge_mod.NoApiKey as exc:
            skipped_tier2 = True
            if not args.json:
                console.print(f"[yellow]Tier 2 skipped:[/yellow] {exc}")
        else:
            if not args.json:
                table = Table(title="Tier 2 — rubric-judged", header_style="bold")
                table.add_column(""); table.add_column("Case")
                table.add_column("Score"); table.add_column("Reasoning", overflow="fold")
                for j in judgements:
                    table.add_row(
                        "[green]PASS[/green]" if j.passed else "[red]FAIL[/red]",
                        j.case_id, f"{j.score}/5 (need {j.min_score})", j.reasoning,
                    )
                console.print(table)

    mutations_ok = True
    if args.mutations:
        mutations_ok = _run_mutations(cases)

    if args.json:
        print(json.dumps({
            "tier1": [
                {"case": r.case_id, "passed": r.passed, "expected": r.expected,
                 "actual": r.actual, "detail": r.detail}
                for r in results
            ],
            "tier2": [
                {"case": j.case_id, "score": j.score, "min_score": j.min_score,
                 "passed": j.passed, "reasoning": j.reasoning,
                 "violations": j.violations}
                for j in judgements
            ],
            "tier2_skipped": skipped_tier2,
            "mutations_all_caught": mutations_ok if args.mutations else None,
        }, indent=2))
    else:
        failed_t2 = [j for j in judgements if not j.passed]
        console.print(
            f"\nTier 1: {len(results) - len(failed)}/{len(results)} passed."
            + (f"  Tier 2: {len(judgements) - len(failed_t2)}/{len(judgements)} passed."
               if judgements else "")
        )

    if not mutations_ok:
        return 2
    if failed or any(not j.passed for j in judgements):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
