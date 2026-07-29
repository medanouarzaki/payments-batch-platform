"""Does processing order matter for a multi-day backfill?

Each of the five days' rows is generated exactly once and reused as-is in
both phases below. Chronological processing lands and builds day 1, then
day 2, ... into one warehouse; reverse processing lands and builds the same
five row sets from day 5 down to day 1 into a second, independent warehouse
and raw-transactions tree, so partitions are only ever visible to dbt in the
order each phase actually landed them - matching how the real DAG would see
a chronological run versus a backfill run in the opposite order. Both
warehouses are checked for internal consistency (reconciliation and date
coverage) regardless of what the order comparison in T4 below finds.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from payments.generator import build_daily_batch
from payments.ingestion import land_batch

RUN_DATES: tuple[date, ...] = tuple(date(2026, 5, 1) + timedelta(days=i) for i in range(5))

MARTS: tuple[str, ...] = (
    "fct_transactions",
    "agg_transactions_daily",
    "agg_fx_exposure_daily",
    "data_quality_daily",
)


def _table_fingerprint(con: duckdb.DuckDBPyConnection, table: str) -> str:
    query = (
        f"select md5(string_agg(h, '' order by h)) "
        f"from (select md5(x::varchar) as h from {table} x)"
    )
    return con.sql(query).fetchone()[0]


def _snapshot(warehouse_path: Path) -> dict[str, tuple[int, str]]:
    con = duckdb.connect(str(warehouse_path), read_only=True)
    try:
        return {
            mart: (
                con.sql(f"select count(*) from {mart}").fetchone()[0],
                _table_fingerprint(con, mart),
            )
            for mart in MARTS
        }
    finally:
        con.close()


def _run_daily_dbt_chain(
    run_dbt,
    first_day: bool,
    warehouse_path: Path,
    target_path: Path,
    raw_transactions_dir: Path,
) -> None:
    kwargs = {
        "warehouse_path": warehouse_path,
        "target_path": target_path,
        "raw_transactions_dir": raw_transactions_dir,
    }
    if first_day:
        run_dbt("seed", **kwargs)
    run_dbt("build", "--select", "tag:staging", **kwargs)
    run_dbt("build", "--select", "tag:intermediate", "fct_transactions", **kwargs)
    run_dbt("build", "--select", "tag:marts", "--exclude", "fct_transactions", **kwargs)


def _assert_reconciled_and_covered(warehouse_path: Path, label: str) -> None:
    con = duckdb.connect(str(warehouse_path), read_only=True)
    try:
        ingestion_dates = {
            row[0]
            for row in con.sql("select distinct ingestion_date from data_quality_daily").fetchall()
        }
        assert ingestion_dates == set(RUN_DATES), (
            f"[{label}] data_quality_daily ingestion dates: expected {sorted(RUN_DATES)}, "
            f"observed {sorted(ingestion_dates)}"
        )

        # The generator's late_event defect can date a transaction a few days
        # before its ingestion date, so agg_transactions_daily legitimately
        # covers more event dates than there are ingestion dates: coverage
        # means every run date is represented, not that no other date is.
        event_dates = {
            row[0]
            for row in con.sql(
                "select distinct event_date_utc from agg_transactions_daily"
            ).fetchall()
        }
        assert set(RUN_DATES) <= event_dates, (
            f"[{label}] agg_transactions_daily event dates: expected at least "
            f"{sorted(RUN_DATES)}, observed {sorted(event_dates)}"
        )

        for run_date in RUN_DATES:
            fact_count = con.execute(
                "select count(*) from fct_transactions where event_date_utc = ?", [run_date]
            ).fetchone()[0]
            agg_count = con.execute(
                "select coalesce(sum(transaction_count), 0) from agg_transactions_daily "
                "where event_date_utc = ?",
                [run_date],
            ).fetchone()[0]
            assert agg_count == fact_count, (
                f"[{label}] {run_date}: agg_transactions_daily sums to {agg_count} transactions, "
                f"fct_transactions has {fact_count}"
            )
    finally:
        con.close()


def test_backfill_order_reconciles_both_ways(
    isolated_env, seeded_fx_rates, run_dbt, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows_by_date = {run_date: build_daily_batch(run_date)[0] for run_date in RUN_DATES}

    # --- chronological order: the harness's default raw dir and warehouse ---
    seeded_fx_rates(RUN_DATES[0], RUN_DATES[-1])
    monkeypatch.setenv("PAYMENTS_RAW_TRANSACTIONS_DIR", str(isolated_env.raw_transactions_dir))
    for index, run_date in enumerate(RUN_DATES):
        land_batch(rows_by_date[run_date], run_date)
        _run_daily_dbt_chain(
            run_dbt,
            first_day=index == 0,
            warehouse_path=isolated_env.warehouse_path,
            target_path=isolated_env.target_path,
            raw_transactions_dir=isolated_env.raw_transactions_dir,
        )
    _assert_reconciled_and_covered(isolated_env.warehouse_path, "chronological")
    chronological_snapshot = _snapshot(isolated_env.warehouse_path)

    # --- reverse order: a second, independent raw dir and warehouse ---
    reverse_raw_transactions_dir = isolated_env.data_dir / "raw-reverse" / "transactions"
    reverse_raw_transactions_dir.mkdir(parents=True)
    reverse_warehouse_path = isolated_env.data_dir / "warehouse-reverse.duckdb"
    reverse_target_path = isolated_env.target_path.parent / "dbt-target-reverse"

    seeded_fx_rates(RUN_DATES[0], RUN_DATES[-1], warehouse_path=reverse_warehouse_path)
    monkeypatch.setenv("PAYMENTS_RAW_TRANSACTIONS_DIR", str(reverse_raw_transactions_dir))
    for index, run_date in enumerate(reversed(RUN_DATES)):
        land_batch(rows_by_date[run_date], run_date, base_dir=reverse_raw_transactions_dir)
        _run_daily_dbt_chain(
            run_dbt,
            first_day=index == 0,
            warehouse_path=reverse_warehouse_path,
            target_path=reverse_target_path,
            raw_transactions_dir=reverse_raw_transactions_dir,
        )
    _assert_reconciled_and_covered(reverse_warehouse_path, "reverse")
    reverse_snapshot = _snapshot(reverse_warehouse_path)

    # Measured (see the T4 record in the lot's report): on this five-day scenario,
    # chronological and reverse processing produce byte-identical row counts and
    # table fingerprints on all four tables. The incremental delete+insert models
    # with their sliding dedup_window_days windows are order-invariant here, so
    # chronological order is asserted as the reference an out-of-order backfill
    # must reproduce.
    for mart in MARTS:
        chrono_count, chrono_fp = chronological_snapshot[mart]
        rev_count, rev_fp = reverse_snapshot[mart]
        print(
            f"{mart}: chronological count={chrono_count} fingerprint={chrono_fp} | "
            f"reverse count={rev_count} fingerprint={rev_fp} | "
            f"{'MATCH' if (chrono_count, chrono_fp) == (rev_count, rev_fp) else 'DIVERGENT'}"
        )
        assert (rev_count, rev_fp) == (chrono_count, chrono_fp), (
            f"{mart}: reverse-order backfill diverged from the chronological reference: "
            f"chronological count={chrono_count} fingerprint={chrono_fp}, "
            f"reverse count={rev_count} fingerprint={rev_fp}"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
