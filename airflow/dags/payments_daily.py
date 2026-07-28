"""Daily DAG for the payments batch pipeline.

DuckDB and the payments package are never imported into the Airflow
interpreter: every access to the warehouse runs as a standalone script
executed by /opt/dbt-venv/bin/python, the only environment with those
dependencies pinned and installed.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

from airflow.decorators import dag, task

DBT_VENV_PYTHON = "/opt/dbt-venv/bin/python"
SCRIPTS_DIR = "/opt/airflow/scripts"

default_args = {
    "retries": 2,
    "retry_exponential_backoff": True,
    "retry_delay": timedelta(seconds=30),
    "execution_timeout": timedelta(minutes=10),
    "pool": "warehouse",
    "depends_on_past": False,
}


def _run_script(script_name: str) -> None:
    script_path = f"{SCRIPTS_DIR}/{script_name}"
    result = subprocess.run(
        [DBT_VENV_PYTHON, script_path],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(
            f"{script_name} failed with exit code {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


@dag(
    dag_id="payments_daily",
    schedule="@daily",
    start_date=datetime(2026, 4, 1, tzinfo=UTC),
    catchup=True,
    max_active_runs=1,
    default_args=default_args,
    tags=["payments", "dbt", "warehouse"],
)
def payments_daily():
    @task
    def preflight() -> None:
        _run_script("preflight_check.py")

    @task
    def run_summary() -> None:
        _run_script("warehouse_summary.py")

    preflight() >> run_summary()


payments_daily()
