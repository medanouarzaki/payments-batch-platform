"""Shared fixtures for offline, filesystem-isolated integration tests.

Every fixture here confines reads and writes to pytest's tmp_path: the
project root stays the real repository (so config/defects.yml and the dbt
project are found), but the data directory, the warehouse, and the dbt
target all live under the temporary directory.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from payments.fx.cache import FxRateRow, create_schema, upsert_rows

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = REPO_ROOT / "dbt"
DBT_VENV_DBT = os.environ.get("DBT_VENV_DBT_BIN", str(REPO_ROOT / ".venv" / "bin" / "dbt"))

QUOTE_CURRENCIES: tuple[str, ...] = ("CAD", "CHF", "GBP", "JPY", "MAD")
FIXED_RATES: dict[str, float] = {
    "CAD": 1.6,
    "CHF": 0.92,
    "GBP": 0.87,
    "JPY": 186.0,
    "MAD": 10.8,
}


@dataclass(frozen=True)
class IsolatedEnv:
    data_dir: Path
    raw_transactions_dir: Path
    warehouse_path: Path
    target_path: Path


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> IsolatedEnv:
    data_dir = tmp_path / "data"
    raw_transactions_dir = data_dir / "raw" / "transactions"
    warehouse_path = data_dir / "warehouse.duckdb"
    target_path = tmp_path / "dbt-target"

    raw_transactions_dir.mkdir(parents=True)
    data_dir.mkdir(exist_ok=True)

    monkeypatch.setenv("PAYMENTS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PAYMENTS_RAW_TRANSACTIONS_DIR", str(raw_transactions_dir))
    monkeypatch.setenv("PAYMENTS_WAREHOUSE_PATH", str(warehouse_path))
    monkeypatch.setenv("PAYMENTS_ROWS_MIN", "200")
    monkeypatch.setenv("PAYMENTS_ROWS_MAX", "300")

    return IsolatedEnv(
        data_dir=data_dir,
        raw_transactions_dir=raw_transactions_dir,
        warehouse_path=warehouse_path,
        target_path=target_path,
    )


@pytest.fixture
def seeded_fx_rates(isolated_env: IsolatedEnv):
    def _seed(window_start: date, window_end: date, base_currency: str = "EUR") -> None:
        con = duckdb.connect(str(isolated_env.warehouse_path))
        create_schema(con)

        fetched_at = datetime.now(UTC)
        rows: list[FxRateRow] = []
        current = window_start
        while current <= window_end:
            for currency in QUOTE_CURRENCIES:
                rows.append(
                    FxRateRow(
                        rate_date=current,
                        quote_currency=currency,
                        base_currency=base_currency,
                        rate=FIXED_RATES[currency],
                        effective_rate_date=current,
                        is_carried_forward=False,
                        fx_status="ok",
                        unavailable_reason=None,
                        fetched_at=fetched_at,
                    )
                )
            current += timedelta(days=1)

        upsert_rows(con, rows)
        con.close()

    return _seed


@pytest.fixture
def run_dbt(isolated_env: IsolatedEnv) -> Iterator[callable]:
    def _run(*args: str) -> None:
        env = dict(os.environ)
        env["PAYMENTS_WAREHOUSE_PATH"] = str(isolated_env.warehouse_path)
        env["PAYMENTS_RAW_TRANSACTIONS_DIR"] = str(isolated_env.raw_transactions_dir)
        env["DBT_PROFILES_DIR"] = str(DBT_PROJECT_DIR)

        indirect_selection = ["--indirect-selection", "buildable"] if args[0] == "build" else []
        result = subprocess.run(
            [
                DBT_VENV_DBT,
                *args,
                *indirect_selection,
                "--project-dir",
                str(DBT_PROJECT_DIR),
                "--target-path",
                str(isolated_env.target_path),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"dbt {args} failed with exit code {result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

    yield _run


def table_fingerprint(con: duckdb.DuckDBPyConnection, table: str) -> str:
    query = (
        f"select md5(string_agg(h, '' order by h)) "
        f"from (select md5(x::varchar) as h from {table} x)"
    )
    return con.sql(query).fetchone()[0]
