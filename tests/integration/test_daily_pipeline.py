"""End-to-end, offline coverage of three consecutive days of the pipeline.

Generates and lands three days of synthetic transactions, seeds fixed
exchange rates for the same window, runs the dbt chain once per day in
chronological order, and checks that the warehouse reconciles.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from payments.generator import build_daily_batch
from payments.ingestion import land_batch

RUN_DATES: tuple[date, ...] = (date(2026, 2, 1), date(2026, 2, 2), date(2026, 2, 3))

MARTS: tuple[str, ...] = (
    "fct_transactions",
    "agg_transactions_daily",
    "agg_fx_exposure_daily",
    "data_quality_daily",
)


def _run_daily_dbt_chain(run_dbt, first_day: bool) -> None:
    if first_day:
        run_dbt("seed")
    run_dbt("build", "--select", "tag:staging")
    run_dbt("build", "--select", "tag:intermediate", "fct_transactions")
    run_dbt("build", "--select", "tag:marts", "--exclude", "fct_transactions")


def _table_fingerprint(con: duckdb.DuckDBPyConnection, table: str) -> str:
    query = (
        f"select md5(string_agg(h, '' order by h)) "
        f"from (select md5(x::varchar) as h from {table} x)"
    )
    return con.sql(query).fetchone()[0]


def test_three_consecutive_days_end_to_end(isolated_env, seeded_fx_rates, run_dbt) -> None:
    seeded_fx_rates(RUN_DATES[0], RUN_DATES[-1])

    for index, run_date in enumerate(RUN_DATES):
        rows, _report = build_daily_batch(run_date)
        land_batch(rows, run_date)
        _run_daily_dbt_chain(run_dbt, first_day=index == 0)

    con = duckdb.connect(str(isolated_env.warehouse_path), read_only=True)
    try:
        for mart in MARTS:
            row_count = con.sql(f"select count(*) from {mart}").fetchone()[0]
            assert row_count > 0, f"{mart} has no rows after three days"
            print(mart, row_count, _table_fingerprint(con, mart))

        ingestion_dates = con.sql(
            "select count(distinct ingestion_date) from data_quality_daily"
        ).fetchone()[0]
        assert ingestion_dates == 3, (
            f"expected 3 distinct ingestion dates in data_quality_daily, got {ingestion_dates}"
        )

        rows = con.sql(
            "select ingestion_date, received_row_count, valid_row_count, "
            "quarantined_row_count from data_quality_daily order by ingestion_date"
        ).fetchall()
        for ingestion_date, received, valid, quarantined in rows:
            assert received == valid + quarantined, (
                f"accounting mismatch on {ingestion_date}: "
                f"received={received} valid={valid} quarantined={quarantined}"
            )
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
