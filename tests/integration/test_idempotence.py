"""Replaying an already-processed day must not change the warehouse.

Builds three consecutive days, records table fingerprints and row counts,
then replays the most recent day and the oldest day - regeneration and
landing included, no --full-refresh - and requires identical fingerprints
and counts after each replay.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from payments.generator import build_daily_batch
from payments.ingestion import land_batch
from payments.publish.fingerprint import table_fingerprint

RUN_DATES: tuple[date, ...] = (date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3))

MARTS: tuple[str, ...] = (
    "fct_transactions",
    "agg_transactions_daily",
    "agg_fx_exposure_daily",
    "data_quality_daily",
    "agg_transactions_channel_daily",
)


def _snapshot(warehouse_path) -> dict[str, tuple[int, str]]:
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


def _run_daily_dbt_chain(run_dbt, first_day: bool) -> None:
    if first_day:
        run_dbt("seed")
    run_dbt("build", "--select", "tag:staging")
    run_dbt("build", "--select", "tag:intermediate", "fct_transactions")
    run_dbt("build", "--select", "tag:marts", "--exclude", "fct_transactions")


def _generate_and_land(run_date: date) -> None:
    rows, _report = build_daily_batch(run_date)
    land_batch(rows, run_date)


def _assert_snapshot_unchanged(
    before: dict[str, tuple[int, str]], after: dict[str, tuple[int, str]], replayed_date: date
) -> None:
    for mart in MARTS:
        expected_count, expected_fingerprint = before[mart]
        observed_count, observed_fingerprint = after[mart]
        assert observed_count == expected_count, (
            f"{mart} row count changed after replaying {replayed_date}: "
            f"expected {expected_count}, observed {observed_count}"
        )
        assert observed_fingerprint == expected_fingerprint, (
            f"{mart} fingerprint changed after replaying {replayed_date}: "
            f"expected {expected_fingerprint}, observed {observed_fingerprint}"
        )


def test_replaying_a_day_is_idempotent(isolated_env, seeded_fx_rates, run_dbt) -> None:
    seeded_fx_rates(RUN_DATES[0], RUN_DATES[-1])

    for index, run_date in enumerate(RUN_DATES):
        _generate_and_land(run_date)
        _run_daily_dbt_chain(run_dbt, first_day=index == 0)

    snapshot_after_initial_build = _snapshot(isolated_env.warehouse_path)

    latest_day = RUN_DATES[-1]
    _generate_and_land(latest_day)
    _run_daily_dbt_chain(run_dbt, first_day=False)
    snapshot_after_latest_replay = _snapshot(isolated_env.warehouse_path)
    _assert_snapshot_unchanged(
        snapshot_after_initial_build, snapshot_after_latest_replay, latest_day
    )

    earliest_day = RUN_DATES[0]
    _generate_and_land(earliest_day)
    _run_daily_dbt_chain(run_dbt, first_day=False)
    snapshot_after_earliest_replay = _snapshot(isolated_env.warehouse_path)
    _assert_snapshot_unchanged(
        snapshot_after_initial_build, snapshot_after_earliest_replay, earliest_day
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
