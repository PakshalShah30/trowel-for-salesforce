"""Week 3: the SQLite catalog.

Why SQLite and not the graph alone (FRAMEWORK §3)
--------------------------------------------------
The graph answers reachability questions — "what breaks if I delete this?" —
and it answers them in one traversal. It is a poor place to answer "show me
every Active Flow on Lead, sorted by name", which is a filter over a table.

So both exist and each does what it is good at: the table is the inventory and
the durable artifact between runs; the graph is derived from it in memory,
cheaply, whenever a reachability question is asked. Rebuilding the graph from
the table costs milliseconds at org scale and removes any chance of the two
disagreeing — the alternative, persisting the graph too, buys nothing and
introduces a cache to invalidate.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Artifact, Edge, Kind, Reference

SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    id       TEXT PRIMARY KEY,
    kind     TEXT NOT NULL,
    name     TEXT NOT NULL,
    status   TEXT,
    subtype  TEXT,
    path     TEXT,
    attrs    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS references_ (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge      TEXT NOT NULL,
    detail    TEXT,
    PRIMARY KEY (source_id, target_id, edge, detail)
);

CREATE INDEX IF NOT EXISTS idx_refs_target ON references_(target_id);
CREATE INDEX IF NOT EXISTS idx_refs_source ON references_(source_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts(kind);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def write(conn: sqlite3.Connection, artifacts: list[Artifact],
          references: list[Reference]) -> None:
    """Replace the catalog contents.

    A full replace, not an upsert: an excavation is a snapshot of the org at a
    moment, and a partial merge would leave deleted metadata sitting in the
    catalog looking alive. Diffing two snapshots is a separate feature
    (the Time Machine in the enhancement backlog) and wants both kept whole.
    """
    with conn:
        conn.execute("DELETE FROM artifacts")
        conn.execute("DELETE FROM references_")
        conn.executemany(
            "INSERT OR REPLACE INTO artifacts (id, kind, name, status, subtype, path, attrs)"
            " VALUES (?,?,?,?,?,?,?)",
            [(a.id, a.kind.value, a.name, a.status, a.subtype, a.path, json.dumps(a.attrs))
             for a in artifacts],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO references_ (source_id, target_id, edge, detail)"
            " VALUES (?,?,?,?)",
            [(r.source_id, r.target_id, r.edge.value, r.detail) for r in references],
        )


def read_artifacts(conn: sqlite3.Connection) -> list[Artifact]:
    rows = conn.execute("SELECT * FROM artifacts ORDER BY id").fetchall()
    return [
        Artifact(
            id=r["id"], kind=Kind(r["kind"]), name=r["name"], status=r["status"],
            subtype=r["subtype"], path=r["path"], attrs=json.loads(r["attrs"]),
        )
        for r in rows
    ]


def read_references(conn: sqlite3.Connection) -> list[Reference]:
    rows = conn.execute(
        "SELECT * FROM references_ ORDER BY source_id, target_id"
    ).fetchall()
    return [
        Reference(r["source_id"], r["target_id"], Edge(r["edge"]), r["detail"])
        for r in rows
    ]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    out = {
        row["kind"]: row["n"]
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM artifacts GROUP BY kind ORDER BY kind"
        )
    }
    out["references"] = conn.execute(
        "SELECT COUNT(*) AS n FROM references_"
    ).fetchone()["n"]
    return out
