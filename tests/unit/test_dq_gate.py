from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb

GATE = str(Path(__file__).resolve().parents[2] / "airflow" / "scripts" / "dq_gate.py")

INGESTION_DATE = "2026-06-01"


def _make_warehouse(db_path: Path, row: dict) -> None:
    con = duckdb.connect(str(db_path))
    con.execute(
        "create table data_quality_daily ("
        "ingestion_date date, "
        "received_row_count bigint, "
        "valid_row_count bigint, "
        "quarantined_row_count bigint, "
        "rejection_rate double"
        ")"
    )
    if row is not None:
        con.execute(
            "insert into data_quality_daily values (?, ?, ?, ?, ?)",
            [
                row["ingestion_date"],
                row["received_row_count"],
                row["valid_row_count"],
                row["quarantined_row_count"],
                row["rejection_rate"],
            ],
        )
    con.close()


def _run_gate(db_path: Path, threshold: float) -> subprocess.CompletedProcess:
    env = {"PAYMENTS_WAREHOUSE_PATH": str(db_path), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [
            sys.executable,
            GATE,
            "--ingestion-date",
            INGESTION_DATE,
            "--threshold",
            str(threshold),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def test_exits_nonzero_and_reports_when_quarantine_rate_exceeds_threshold(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    _make_warehouse(
        db_path,
        {
            "ingestion_date": INGESTION_DATE,
            "received_row_count": 100,
            "valid_row_count": 90,
            "quarantined_row_count": 10,
            "rejection_rate": 0.10,
        },
    )

    result = _run_gate(db_path, threshold=0.05)

    assert result.returncode == 1
    assert "exceeds threshold" in result.stderr


def test_exits_zero_when_quarantine_rate_is_within_threshold(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    _make_warehouse(
        db_path,
        {
            "ingestion_date": INGESTION_DATE,
            "received_row_count": 100,
            "valid_row_count": 97,
            "quarantined_row_count": 3,
            "rejection_rate": 0.03,
        },
    )

    result = _run_gate(db_path, threshold=0.05)

    assert result.returncode == 0


def test_exits_nonzero_when_no_row_exists_for_the_requested_date(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    _make_warehouse(db_path, None)

    result = _run_gate(db_path, threshold=0.05)

    assert result.returncode == 1


def test_exits_nonzero_when_received_does_not_equal_valid_plus_quarantined(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    _make_warehouse(
        db_path,
        {
            "ingestion_date": INGESTION_DATE,
            "received_row_count": 100,
            "valid_row_count": 90,
            "quarantined_row_count": 5,
            "rejection_rate": 0.05,
        },
    )

    result = _run_gate(db_path, threshold=0.10)

    assert result.returncode == 1
