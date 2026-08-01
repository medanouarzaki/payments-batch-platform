"""Publish serving marts as versioned CSV files, with a manifest.

The serving file (see export_marts.py) already isolates dashboard readers
from the warehouse writer, but it still requires a DuckDB runtime to read.
This module goes one step further: it turns the serving file's tables into
plain CSV files that can be committed to the repository and served to a
static, public dashboard without any database at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from payments.publish.export_marts import SERVING_TABLES
from payments.publish.fingerprint import table_fingerprint

MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class TableSnapshot:
    name: str
    rows: int
    fingerprint: str
    csv_file: str


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_dir: Path
    manifest_path: Path
    tables: tuple[TableSnapshot, ...]


def _export_table_csv(con: duckdb.DuckDBPyConnection, table: str, csv_path: Path) -> None:
    # "order by all" makes row order a function of the data, not of storage
    # order, so re-running the export against an equivalent but differently
    # ordered source still yields byte-identical CSV output.
    con.execute(
        f"copy (select * from \"{table}\" order by all) to '{csv_path}' (header, delimiter ',')"
    )


def export_snapshot(serving_path: Path, snapshot_dir: Path) -> SnapshotResult:
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    published_at = datetime.fromtimestamp(serving_path.stat().st_mtime, tz=UTC)

    con = duckdb.connect(str(serving_path), read_only=True)
    try:
        tables: list[TableSnapshot] = []
        for table in sorted(SERVING_TABLES):
            csv_file = f"{table}.csv"
            _export_table_csv(con, table, snapshot_dir / csv_file)
            rows = con.execute(f'select count(*) from "{table}"').fetchone()[0]
            fingerprint = table_fingerprint(con, table)
            tables.append(
                TableSnapshot(name=table, rows=rows, fingerprint=fingerprint, csv_file=csv_file)
            )
    finally:
        con.close()

    manifest = {
        "duckdb_version": duckdb.__version__,
        "serving_published_at": published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tables": [
            {
                "name": t.name,
                "rows": t.rows,
                "fingerprint": t.fingerprint,
                "csv_file": t.csv_file,
            }
            for t in tables
        ],
    }

    manifest_path = snapshot_dir / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return SnapshotResult(
        snapshot_dir=snapshot_dir, manifest_path=manifest_path, tables=tuple(tables)
    )
