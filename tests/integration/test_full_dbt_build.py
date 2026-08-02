"""Build the whole dbt project once, offline, and check every declared test ran.

Lands three consecutive days of synthetic transactions and fixed fx rates,
then runs `dbt seed` followed by a single unselected `dbt build`. The check
reads dbt's structured run_results.json rather than parsing console output,
since ANSI codes and message wording are not a stable thing to match on.
"""

from __future__ import annotations

import json
from datetime import date

from payments.generator import build_daily_batch
from payments.ingestion import land_batch

RUN_DATES: tuple[date, ...] = (date(2026, 2, 1), date(2026, 2, 2), date(2026, 2, 3))

EXPECTED_DBT_TEST_COUNT = 79


def test_full_build_runs_every_declared_test(isolated_env, seeded_fx_rates, run_dbt) -> None:
    seeded_fx_rates(RUN_DATES[0], RUN_DATES[-1])

    for run_date in RUN_DATES:
        rows, _report = build_daily_batch(run_date)
        land_batch(rows, run_date)

    run_dbt("seed")
    run_dbt("build")

    run_results_path = isolated_env.target_path / "run_results.json"
    run_results = json.loads(run_results_path.read_text())
    results = run_results["results"]

    test_results = [r for r in results if r["unique_id"].startswith("test.")]
    non_test_results = [r for r in results if not r["unique_id"].startswith("test.")]

    assert len(test_results) == EXPECTED_DBT_TEST_COUNT, (
        f"expected {EXPECTED_DBT_TEST_COUNT} dbt tests to run, got {len(test_results)}: "
        f"{sorted(r['unique_id'] for r in test_results)}"
    )

    failed_tests = [r for r in test_results if r["status"] != "pass"]
    assert not failed_tests, "dbt tests failed: " + ", ".join(
        f"{r['unique_id']} (status={r['status']})" for r in failed_tests
    )

    failed_nodes = [r for r in non_test_results if r["status"] != "success"]
    assert not failed_nodes, "dbt models or seeds failed: " + ", ".join(
        f"{r['unique_id']} (status={r['status']})" for r in failed_nodes
    )
