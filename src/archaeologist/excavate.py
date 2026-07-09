"""Week 1–3: pull org metadata via the sf CLI and stage it for parsing.

Usage:
    python -m archaeologist.excavate --org dig-site

Design note (FRAMEWORK §2): we shell out to the official `sf` CLI rather than
calling APIs directly — same tooling as CI/CD pipelines, read-only, and the
retrieved XML tree is exactly what version control sees.
"""

import argparse
import subprocess
import sys
from pathlib import Path

RETRIEVE_DIR = Path("dig-site-sample")

# Start narrow; widen as the parser (week 3) learns each type.
METADATA_TYPES = [
    "Flow",
    "ApexClass",
    "ApexTrigger",
    "CustomObject",
    "PermissionSet",
    "ValidationRule",
]


def excavate(org_alias: str) -> None:
    RETRIEVE_DIR.mkdir(exist_ok=True)
    metadata_args = []
    for t in METADATA_TYPES:
        metadata_args += ["--metadata", t]
    cmd = [
        "sf", "project", "retrieve", "start",
        "--target-org", org_alias,
        "--output-dir", str(RETRIEVE_DIR),
        *metadata_args,
    ]
    print(f"⛏️  Excavating {org_alias} → {RETRIEVE_DIR}/")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    files = list(RETRIEVE_DIR.rglob("*.xml"))
    print(f"✅ Retrieved {len(files)} artifacts. Go read a few — that's week 1.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", default="dig-site")
    args = parser.parse_args()
    excavate(args.org)
