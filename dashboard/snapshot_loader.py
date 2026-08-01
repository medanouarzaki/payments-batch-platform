"""Reconstruct a DuckDB database from the CSV snapshot under dashboard/snapshot/.

The public entry point never opens the internal serving file: it rebuilds an
equivalent, disposable database from committed CSV files and their manifest,
so it can run from a bare checkout that has no access to the data pipeline.
Column types come from the manifest, never from DuckDB's own CSV sniffer,
because sniffing alone would turn DECIMAL columns into DOUBLE and lose
precision (see the divergence measured for the manifest's own column list).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import duckdb


def build_database_from_snapshot(snapshot_dir: Path) -> Path:
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"snapshot manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    workdir = Path(tempfile.mkdtemp(prefix="payments-snapshot-"))
    database_path = workdir / "snapshot.duckdb"

    con = duckdb.connect(str(database_path))
    try:
        for entry in manifest["tables"]:
            csv_path = snapshot_dir / entry["csv_file"]
            if not csv_path.is_file():
                raise FileNotFoundError(f"snapshot csv not found: {csv_path}")

            ddl = ", ".join(f'"{column["name"]}" {column["type"]}' for column in entry["columns"])
            con.execute(f'create table "{entry["name"]}" ({ddl})')
            con.execute(f"copy \"{entry['name']}\" from '{csv_path}' (header, delimiter ',')")
    finally:
        con.close()

    return database_path
