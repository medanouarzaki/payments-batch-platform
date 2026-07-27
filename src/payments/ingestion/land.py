"""Atomic Parquet landing of a daily batch into a Hive-style partition."""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from payments.config import get_settings
from payments.generator.schema import RAW_COLUMNS

PARQUET_COLUMNS: tuple[str, ...] = tuple(
    column for column in RAW_COLUMNS if column != "ingestion_date"
)

PARQUET_SCHEMA: pa.Schema = pa.schema(
    [
        (column, pa.timestamp("us", tz="UTC")) if column == "ingested_at" else (column, pa.string())
        for column in PARQUET_COLUMNS
    ]
)


class LandingError(Exception):
    """Raised when a batch cannot be safely landed to a partition."""


@dataclass(frozen=True)
class LandingResult:
    path: Path
    rows: int
    bytes_written: int
    sha256: str


def partition_path(run_date: date, base_dir: Path | None = None) -> Path:
    base = base_dir if base_dir is not None else get_settings().raw_transactions_dir
    return base / f"ingestion_date={run_date.isoformat()}"


def land_batch(rows: list[dict], run_date: date, base_dir: Path | None = None) -> LandingResult:
    for row in rows:
        if row["ingestion_date"] != run_date:
            raise LandingError(
                f"row ingestion_date {row['ingestion_date']!r} does not match run_date {run_date!r}"
            )

    raw_transactions_dir = get_settings().raw_transactions_dir
    partition = partition_path(run_date, base_dir)

    resolved_partition = partition.resolve()
    resolved_root = raw_transactions_dir.resolve()
    if not resolved_partition.is_relative_to(resolved_root):
        raise LandingError(
            f"partition path {resolved_partition} is not under raw_transactions_dir {resolved_root}"
        )

    partition.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pylist(
        [{column: row[column] for column in PARQUET_COLUMNS} for row in rows],
        schema=PARQUET_SCHEMA,
    )

    final_path = partition / "part-0000.parquet"
    tmp_path = partition / "part-0000.parquet.tmp"

    # Write-then-swap: the new file is written and fully flushed before any
    # existing content in the partition is touched. Only once the write below
    # has succeeded do we discard whatever the partition held before, so a
    # failed write never destroys previously landed data. The swap itself is
    # a single os.replace(), which is atomic: final_path points either at the
    # old complete file or at the new one, never at nothing and never at a
    # partial write. Only after that swap has landed do we clear out
    # whatever else the partition held, so even a failure during that final
    # cleanup leaves final_path already holding the new data, not the old
    # data or an empty partition.
    try:
        pq.write_table(table, tmp_path, compression="snappy")
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    try:
        os.replace(tmp_path, final_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    for existing in partition.iterdir():
        if existing == final_path:
            continue
        if existing.is_dir():
            shutil.rmtree(existing)
        else:
            existing.unlink()

    data = final_path.read_bytes()
    return LandingResult(
        path=final_path,
        rows=len(rows),
        bytes_written=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
