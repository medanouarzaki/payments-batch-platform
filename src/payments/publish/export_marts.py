"""Publish warehouse marts to a separate, read-only-friendly serving file.

DuckDB refuses any reader, even a read-only one, while a writer holds the
warehouse file open. Dashboards and other read-heavy consumers must therefore
not open data/warehouse.duckdb directly: this module copies the tables they
need into a small, independent file that can be read concurrently with dbt
writing to the warehouse.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import duckdb

SERVING_TABLES: tuple[str, ...] = (
    "agg_transactions_daily",
    "agg_transactions_channel_daily",
    "agg_fx_exposure_daily",
    "data_quality_daily",
    "dim_country",
    "dim_currency",
)


def _copy_table(con: duckdb.DuckDBPyConnection, table: str) -> int:
    con.execute(f"create table {table} as select * from wh.{table}")
    return con.execute(f"select count(*) from {table}").fetchone()[0]


@dataclass(frozen=True)
class ExportResult:
    serving_path: Path
    row_counts: dict[str, int]


def export_marts(warehouse_path: Path, serving_path: Path) -> ExportResult:
    serving_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = serving_path.parent / (serving_path.name + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    con: duckdb.DuckDBPyConnection | None = None
    try:
        con = duckdb.connect(str(tmp_path))
        con.execute(f"attach '{warehouse_path}' as wh (read_only)")

        row_counts: dict[str, int] = {}
        for table in SERVING_TABLES:
            row_counts[table] = _copy_table(con, table)

        con.execute("detach wh")
        con.close()
        con = None

        os.replace(tmp_path, serving_path)
    finally:
        if con is not None:
            con.close()
        if tmp_path.exists():
            tmp_path.unlink()

    return ExportResult(serving_path=serving_path, row_counts=row_counts)
