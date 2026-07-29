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
import yaml

from payments.generator import build_daily_batch
from payments.ingestion import land_batch
from payments.publish.fingerprint import table_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[2]
DEDUP_WINDOW_DAYS: int = yaml.safe_load((REPO_ROOT / "dbt" / "dbt_project.yml").read_text())[
    "vars"
]["dedup_window_days"]

RUN_DATES: tuple[date, ...] = tuple(date(2026, 5, 1) + timedelta(days=i) for i in range(5))

MARTS: tuple[str, ...] = (
    "fct_transactions",
    "agg_transactions_daily",
    "agg_fx_exposure_daily",
    "data_quality_daily",
)


def _snapshot(warehouse_path: Path) -> dict[str, tuple[int, str]]:
    con = duckdb.connect(str(warehouse_path), read_only=True)
    try:
        return {
            mart: (
                con.sql(f"select count(*) from {mart}").fetchone()[0],
                table_fingerprint(con, mart),
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
    # table fingerprints on all four tables. This convergence is an artefact of
    # the scenario being shorter than dedup_window_days (7): no partition can
    # fall outside the window in either order. It is not evidence that order is
    # irrelevant in general - see
    # test_backfill_reverse_order_drops_partitions_older_than_window, which
    # shows the two orders diverge once the span exceeds the window.
    # Chronological order is asserted here as the reference an out-of-order
    # backfill within the window must reproduce.
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


def _dq_ingestion_dates(warehouse_path: Path) -> set[date]:
    con = duckdb.connect(str(warehouse_path), read_only=True)
    try:
        return {
            row[0]
            for row in con.sql("select distinct ingestion_date from data_quality_daily").fetchall()
        }
    finally:
        con.close()


EXTENDED_RUN_DATES: tuple[date, ...] = tuple(
    date(2026, 4, 1) + timedelta(days=i) for i in range(DEDUP_WINDOW_DAYS + 4)
)


def test_backfill_reverse_order_drops_partitions_older_than_window(
    isolated_env, seeded_fx_rates, run_dbt, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known limitation, not desired behaviour.

    Over a span of DEDUP_WINDOW_DAYS + 4 days, chronological processing
    covers every ingestion date, but reverse (newest-first) processing
    permanently loses the oldest DEDUP_WINDOW_DAYS + 4 - DEDUP_WINDOW_DAYS
    days: the very first reverse run fixes max(ingestion_date) at the
    newest day, pinning window_start that many days later, so any older
    day lands outside the window from its first attempt and is never
    reintegrated. This documents why depends_on_past=True (chronological
    order) is a correctness requirement for backfills, not an operational
    nicety.
    """
    rows_by_date = {run_date: build_daily_batch(run_date)[0] for run_date in EXTENDED_RUN_DATES}

    seeded_fx_rates(EXTENDED_RUN_DATES[0], EXTENDED_RUN_DATES[-1])
    monkeypatch.setenv("PAYMENTS_RAW_TRANSACTIONS_DIR", str(isolated_env.raw_transactions_dir))
    for index, run_date in enumerate(EXTENDED_RUN_DATES):
        land_batch(rows_by_date[run_date], run_date)
        _run_daily_dbt_chain(
            run_dbt,
            first_day=index == 0,
            warehouse_path=isolated_env.warehouse_path,
            target_path=isolated_env.target_path,
            raw_transactions_dir=isolated_env.raw_transactions_dir,
        )
    chronological_snapshot = _snapshot(isolated_env.warehouse_path)
    chrono_dq_dates = _dq_ingestion_dates(isolated_env.warehouse_path)

    reverse_raw_transactions_dir = isolated_env.data_dir / "raw-reverse" / "transactions"
    reverse_raw_transactions_dir.mkdir(parents=True)
    reverse_warehouse_path = isolated_env.data_dir / "warehouse-reverse.duckdb"
    reverse_target_path = isolated_env.target_path.parent / "dbt-target-reverse"

    seeded_fx_rates(
        EXTENDED_RUN_DATES[0], EXTENDED_RUN_DATES[-1], warehouse_path=reverse_warehouse_path
    )
    monkeypatch.setenv("PAYMENTS_RAW_TRANSACTIONS_DIR", str(reverse_raw_transactions_dir))
    for index, run_date in enumerate(reversed(EXTENDED_RUN_DATES)):
        land_batch(rows_by_date[run_date], run_date, base_dir=reverse_raw_transactions_dir)
        _run_daily_dbt_chain(
            run_dbt,
            first_day=index == 0,
            warehouse_path=reverse_warehouse_path,
            target_path=reverse_target_path,
            raw_transactions_dir=reverse_raw_transactions_dir,
        )
    reverse_snapshot = _snapshot(reverse_warehouse_path)
    reverse_dq_dates = _dq_ingestion_dates(reverse_warehouse_path)

    print(
        f"\ndedup_window_days={DEDUP_WINDOW_DAYS} "
        f"span={EXTENDED_RUN_DATES[0]}..{EXTENDED_RUN_DATES[-1]} "
        f"({len(EXTENDED_RUN_DATES)} days)"
    )
    for mart in MARTS:
        chrono_count, chrono_fp = chronological_snapshot[mart]
        rev_count, rev_fp = reverse_snapshot[mart]
        print(
            f"{mart}: chronological count={chrono_count} fingerprint={chrono_fp} | "
            f"reverse count={rev_count} fingerprint={rev_fp} | "
            f"{'MATCH' if (chrono_count, chrono_fp) == (rev_count, rev_fp) else 'DIVERGENT'}"
        )
    print(f"chronological data_quality_daily ingestion_dates: {sorted(chrono_dq_dates)}")
    print(f"reverse data_quality_daily ingestion_dates: {sorted(reverse_dq_dates)}")

    assert chrono_dq_dates == set(EXTENDED_RUN_DATES), (
        f"chronological data_quality_daily ingestion dates: expected all of "
        f"{sorted(EXTENDED_RUN_DATES)}, observed {sorted(chrono_dq_dates)}"
    )
    assert reverse_dq_dates == set(EXTENDED_RUN_DATES[-DEDUP_WINDOW_DAYS:]), (
        f"reverse data_quality_daily ingestion dates: expected only the last "
        f"{DEDUP_WINDOW_DAYS} days {sorted(EXTENDED_RUN_DATES[-DEDUP_WINDOW_DAYS:])}, "
        f"observed {sorted(reverse_dq_dates)}"
    )
    assert reverse_dq_dates != chrono_dq_dates, (
        "reverse-order processing was expected to diverge from the "
        "chronological reference over a span beyond the dedup window"
    )
    for mart in MARTS:
        chrono_count, chrono_fp = chronological_snapshot[mart]
        rev_count, rev_fp = reverse_snapshot[mart]
        assert (rev_count, rev_fp) != (chrono_count, chrono_fp), (
            f"{mart}: expected reverse-order processing to diverge from the "
            f"chronological reference beyond the dedup window, but both "
            f"produced count={chrono_count} fingerprint={chrono_fp}"
        )


def test_late_ingestion_beyond_window_is_silently_dropped(
    isolated_env, seeded_fx_rates, run_dbt, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known limitation, not desired behaviour.

    Reproduces the real incident's shape: a recent day is processed first,
    then a day older than the dedup window is ingested. The stale day is
    silently dropped from data_quality_daily and fct_transactions - dbt
    reports no error or warning. Only a downstream gate that requires a
    data_quality_daily row per expected ingestion date (dq_gate) can catch
    this loss.
    """
    recent_date = date(2026, 6, 4)
    stale_date = recent_date - timedelta(days=DEDUP_WINDOW_DAYS + 1)

    rows_recent = build_daily_batch(recent_date)[0]
    rows_stale = build_daily_batch(stale_date)[0]

    seeded_fx_rates(stale_date, recent_date)
    monkeypatch.setenv("PAYMENTS_RAW_TRANSACTIONS_DIR", str(isolated_env.raw_transactions_dir))

    land_batch(rows_recent, recent_date)
    _run_daily_dbt_chain(
        run_dbt,
        first_day=True,
        warehouse_path=isolated_env.warehouse_path,
        target_path=isolated_env.target_path,
        raw_transactions_dir=isolated_env.raw_transactions_dir,
    )
    land_batch(rows_stale, stale_date)
    _run_daily_dbt_chain(
        run_dbt,
        first_day=False,
        warehouse_path=isolated_env.warehouse_path,
        target_path=isolated_env.target_path,
        raw_transactions_dir=isolated_env.raw_transactions_dir,
    )

    dq_dates = _dq_ingestion_dates(isolated_env.warehouse_path)
    con = duckdb.connect(str(isolated_env.warehouse_path), read_only=True)
    try:
        stale_fact_count = con.execute(
            "select count(*) from fct_transactions where source_ingestion_date = ?",
            [stale_date],
        ).fetchone()[0]
    finally:
        con.close()

    print(
        f"\nrecent_date={recent_date} stale_date={stale_date} "
        f"gap_days={(recent_date - stale_date).days} dedup_window_days={DEDUP_WINDOW_DAYS}"
    )
    print(f"data_quality_daily ingestion_dates: {sorted(dq_dates)}")
    print(f"stale_date present in data_quality_daily: {stale_date in dq_dates}")
    print(f"fct_transactions rows for stale_date: {stale_fact_count}")

    assert stale_date not in dq_dates, (
        f"expected {stale_date} to be silently dropped from data_quality_daily "
        f"(known limitation), but it was found: {sorted(dq_dates)}"
    )
    assert stale_fact_count == 0, (
        f"expected 0 fct_transactions rows for the dropped {stale_date}, "
        f"observed {stale_fact_count}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
