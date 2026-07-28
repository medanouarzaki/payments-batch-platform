"""Verify duckdb's version and the presence of the warehouse and raw data.

Run with /opt/dbt-venv/bin/python. Exits non-zero with an explanatory
message on the standard error stream if any check fails.
"""

from __future__ import annotations

import os
import sys

import duckdb

EXPECTED_DUCKDB_VERSION = "1.5.5"

WAREHOUSE_PATH = os.environ.get("PAYMENTS_WAREHOUSE_PATH", "/opt/project/data/warehouse.duckdb")
RAW_TRANSACTIONS_DIR = os.environ.get(
    "PAYMENTS_RAW_TRANSACTIONS_DIR", "/opt/project/data/raw/transactions"
)


def main() -> int:
    if duckdb.__version__ != EXPECTED_DUCKDB_VERSION:
        print(
            f"unexpected duckdb version: {duckdb.__version__}, expected {EXPECTED_DUCKDB_VERSION}",
            file=sys.stderr,
        )
        return 1

    if not os.path.isfile(WAREHOUSE_PATH):
        print(f"warehouse file not found at {WAREHOUSE_PATH}", file=sys.stderr)
        return 1

    if not os.path.isdir(RAW_TRANSACTIONS_DIR):
        print(
            f"raw transactions directory not found at {RAW_TRANSACTIONS_DIR}",
            file=sys.stderr,
        )
        return 1

    print("duckdb", duckdb.__version__)
    print(f"warehouse present at {WAREHOUSE_PATH}")
    print(f"raw transactions dir present at {RAW_TRANSACTIONS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
