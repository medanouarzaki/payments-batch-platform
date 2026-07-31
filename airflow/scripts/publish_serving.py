"""Publish the warehouse marts to the serving file.

Run with /opt/dbt-venv/bin/python. Opens the warehouse read-only and writes
the serving file atomically via payments.publish.export_marts, the same
function used by the payments export-marts CLI command.
"""

from __future__ import annotations

import json
import sys

import duckdb

from payments.config import get_settings
from payments.publish.export_marts import export_marts


def main() -> int:
    settings = get_settings()
    serving_path = settings.serving_dir / "marts.duckdb"

    result = export_marts(settings.warehouse_path, serving_path)

    summary = dict(result.row_counts)
    summary["duckdb_version"] = duckdb.__version__
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
