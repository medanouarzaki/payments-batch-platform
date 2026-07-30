"""Daily DAG for the payments batch pipeline.

DuckDB and the payments package are never imported into the Airflow
interpreter: every access to the warehouse runs as a standalone script or
CLI invocation executed by /opt/dbt-venv/bin/python, the only environment
with those dependencies pinned and installed.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

from airflow.decorators import dag, task
from airflow.models.param import Param

DBT_VENV_PYTHON = "/opt/dbt-venv/bin/python"
DBT_VENV_DBT = "/opt/dbt-venv/bin/dbt"
SCRIPTS_DIR = "/opt/airflow/scripts"
DBT_PROJECT_DIR = "/opt/project/dbt"

default_args = {
    "retries": 2,
    "retry_exponential_backoff": True,
    "retry_delay": timedelta(seconds=30),
    "execution_timeout": timedelta(minutes=10),
    "pool": "warehouse",
    "depends_on_past": False,
}

DBT_EXECUTION_TIMEOUT = timedelta(minutes=30)


def _run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(
            f"{args} failed with exit code {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout


def _run_script(script_name: str, *extra_args: str) -> str:
    return _run([DBT_VENV_PYTHON, f"{SCRIPTS_DIR}/{script_name}", *extra_args])


def _run_dbt(*args: str) -> str:
    indirect_selection = ["--indirect-selection", "buildable"] if args[0] == "build" else []
    return _run([DBT_VENV_DBT, *args, *indirect_selection, "--project-dir", DBT_PROJECT_DIR])


@dag(
    dag_id="payments_daily",
    schedule="@daily",
    start_date=datetime(2026, 4, 1, tzinfo=UTC),
    catchup=True,
    max_active_runs=1,
    default_args=default_args,
    tags=["payments", "dbt", "warehouse"],
    params={
        "quarantine_threshold": Param(
            0.05,
            type="number",
            description="Share of quarantined rows above which the pipeline should fail.",
        ),
    },
)
def payments_daily():
    @task
    def preflight() -> None:
        _run_script("preflight_check.py")

    @task
    def generate_and_land(logical_date=None) -> None:
        run_date = logical_date.strftime("%Y-%m-%d")
        _run([DBT_VENV_PYTHON, "-m", "payments", "generate", "--date", run_date])

    @task
    def fetch_fx_rates(logical_date=None) -> None:
        run_date = logical_date.strftime("%Y-%m-%d")
        _run([DBT_VENV_PYTHON, "-m", "payments", "fetch-fx", "--date", run_date])

    @task(execution_timeout=DBT_EXECUTION_TIMEOUT, depends_on_past=True)
    def dbt_staging() -> None:
        _run_dbt("seed")
        _run_dbt("build", "--select", "tag:staging")

    @task(execution_timeout=DBT_EXECUTION_TIMEOUT, depends_on_past=True)
    def dbt_intermediate_and_facts() -> None:
        _run_dbt("build", "--select", "tag:intermediate", "fct_transactions")

    @task(execution_timeout=DBT_EXECUTION_TIMEOUT, depends_on_past=True)
    def dbt_marts() -> None:
        _run_dbt("build", "--select", "tag:marts", "--exclude", "fct_transactions")

    @task
    def dq_gate(logical_date=None, params=None) -> None:
        run_date = logical_date.strftime("%Y-%m-%d")
        threshold = str(params["quarantine_threshold"])
        _run_script(
            "dq_gate.py",
            "--ingestion-date",
            run_date,
            "--threshold",
            threshold,
        )

    @task
    def publish_serving() -> None:
        _run_script("publish_serving.py")

    @task
    def run_summary() -> None:
        _run_script("warehouse_summary.py")

    (
        preflight()
        >> generate_and_land()
        >> fetch_fx_rates()
        >> dbt_staging()
        >> dbt_intermediate_and_facts()
        >> dbt_marts()
        >> dq_gate()
        >> publish_serving()
        >> run_summary()
    )


payments_daily()
