"""Print row counts for the four marts as a single line of JSON.

Run with /opt/dbt-venv/bin/python. Opens the warehouse read-only.
"""

from __future__ import annotations

import json
import os
import sys

import duckdb

WAREHOUSE_PATH = os.environ.get("PAYMENTS_WAREHOUSE_PATH", "/opt/project/data/warehouse.duckdb")

MARTS = (
    "fct_transactions",
    "agg_transactions_daily",
    "agg_fx_exposure_daily",
    "data_quality_daily",
)


def main() -> int:
    con = duckdb.connect(WAREHOUSE_PATH, read_only=True)
    summary = {}
    for mart in MARTS:
        summary[mart] = con.sql(f"select count(*) from {mart}").fetchone()[0]
    con.close()
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
