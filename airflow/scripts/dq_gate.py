"""Fail the pipeline when a day's data quality is unacceptable.

Run with /opt/dbt-venv/bin/python. Opens the warehouse read-only and checks,
in order: that a data_quality_daily row exists for the requested date, that
the quarantine rate does not exceed the given threshold, and that the day's
row counts reconcile (received = valid + quarantined).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import duckdb

WAREHOUSE_PATH = os.environ.get("PAYMENTS_WAREHOUSE_PATH", "/opt/project/data/warehouse.duckdb")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingestion-date", required=True)
    parser.add_argument("--threshold", type=float, required=True)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()

    con = duckdb.connect(WAREHOUSE_PATH, read_only=True)
    row = con.sql(
        "select received_row_count, valid_row_count, quarantined_row_count, rejection_rate "
        "from data_quality_daily where ingestion_date = ?",
        params=[args.ingestion_date],
    ).fetchone()
    con.close()

    if row is None:
        print(
            f"no data_quality_daily row found for ingestion_date {args.ingestion_date}",
            file=sys.stderr,
        )
        return 1

    received_row_count, valid_row_count, quarantined_row_count, quarantine_rate = row

    if quarantine_rate > args.threshold:
        print(
            f"quarantine rate {quarantine_rate} exceeds threshold {args.threshold}",
            file=sys.stderr,
        )
        return 1

    expected_received = valid_row_count + quarantined_row_count
    if received_row_count != expected_received:
        print(
            f"accounting mismatch: received_row_count={received_row_count} != "
            f"valid_row_count + quarantined_row_count={expected_received}",
            file=sys.stderr,
        )
        return 1

    summary = {
        "ingestion_date": args.ingestion_date,
        "received_row_count": received_row_count,
        "quarantined_row_count": quarantined_row_count,
        "quarantine_rate": quarantine_rate,
        "threshold": args.threshold,
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
