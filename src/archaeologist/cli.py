"""Week 3 CLI: catalog, inspect, detect.

    python -m archaeologist.cli catalog fixtures/dig-site
    python -m archaeologist.cli stats
    python -m archaeologist.cli detect
    python -m archaeologist.cli impact field:Lead.Score__c

`detect` exits non-zero when it finds anything above 'info', so it can gate a
deployment the same way a linter gates a pull request. A report nobody is
forced to read is a report nobody reads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import catalog as catalog_mod
from . import detectors, graph as graph_mod, parse

DEFAULT_DB = Path("trowel.db")
console = Console()


def _load_graph(db_path: Path):
    conn = catalog_mod.connect(db_path)
    artifacts = catalog_mod.read_artifacts(conn)
    references = catalog_mod.read_references(conn)
    return artifacts, graph_mod.build(artifacts, references)


def cmd_catalog(args) -> int:
    source = Path(args.source)
    if not source.exists():
        console.print(f"[red]No such directory:[/red] {source}")
        return 2
    artifacts, references = parse.parse_tree(source)
    conn = catalog_mod.connect(args.db)
    catalog_mod.write(conn, artifacts, references)
    console.print(f"Cataloged [bold]{len(artifacts)}[/bold] artifacts "
                  f"and [bold]{len(references)}[/bold] references → {args.db}")
    return 0


def cmd_stats(args) -> int:
    conn = catalog_mod.connect(args.db)
    counts = catalog_mod.counts(conn)
    if not counts.get("references") and len(counts) <= 1:
        console.print("[yellow]Catalog is empty. Run `catalog <dir>` first.[/yellow]")
        return 1
    table = Table(title="Catalog", show_header=True, header_style="bold")
    table.add_column("Kind")
    table.add_column("Count", justify="right")
    for key, value in counts.items():
        table.add_row(key, str(value))
    console.print(table)

    _, graph = _load_graph(Path(args.db))
    console.print(graph_mod.stats(graph))
    return 0


def cmd_detect(args) -> int:
    artifacts, graph = _load_graph(Path(args.db))
    findings = detectors.run_all(artifacts, graph)
    if not findings:
        console.print("[green]No findings.[/green]")
        return 0

    colours = {"high": "red", "medium": "yellow", "info": "cyan"}
    for finding in findings:
        colour = colours.get(finding.severity, "white")
        console.print(
            f"[{colour}]{finding.rule}[/{colour}] "
            f"[bold]{finding.severity.upper()}[/bold]  {finding.message}"
        )
        console.print(f"    [dim]{finding.why}[/dim]\n")

    actionable = [f for f in findings if f.severity != "info"]
    console.print(f"{len(findings)} finding(s), {len(actionable)} above info.")
    return 1 if actionable else 0


def cmd_impact(args) -> int:
    _, graph = _load_graph(Path(args.db))
    if args.node not in graph:
        console.print(f"[red]Unknown node:[/red] {args.node}")
        return 2
    affected = graph_mod.impact(graph, args.node)
    if not affected:
        console.print(f"Nothing depends on [bold]{args.node}[/bold].")
        return 0
    console.print(f"Deleting [bold]{args.node}[/bold] would affect {len(affected)}:")
    for node in affected:
        console.print(f"  · {node}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trowel", description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="catalog path")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("catalog", help="parse a metadata tree into the catalog")
    p.add_argument("source", help="retrieved metadata directory")
    p.set_defaults(func=cmd_catalog)

    sub.add_parser("stats", help="catalog and graph summary").set_defaults(func=cmd_stats)
    sub.add_parser("detect", help="run deterministic detectors").set_defaults(func=cmd_detect)

    p = sub.add_parser("impact", help="what breaks if this is deleted")
    p.add_argument("node", help="e.g. field:Lead.Score__c")
    p.set_defaults(func=cmd_impact)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
