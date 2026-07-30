"""Run the dashboard app end to end with streamlit.testing.v1.AppTest."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
from streamlit.testing.v1 import AppTest

_APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


def _build_serving(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        "create table agg_transactions_daily as "
        "select date '2026-01-01' as event_date_utc, 'FR' as debtor_country, "
        "5 as transaction_count, 100.0 as amount_eur_total "
        "union all "
        "select date '2026-01-02' as event_date_utc, 'FR' as debtor_country, "
        "3 as transaction_count, 60.0 as amount_eur_total"
    )
    con.execute(
        "create table agg_transactions_channel_daily as "
        "select date '2026-01-01' as event_date_utc, 'ONLINE' as channel, "
        "'ACCEPTED' as status, 5 as transaction_count, 100.0 as amount_eur_total"
    )
    con.execute(
        "create table agg_fx_exposure_daily as "
        "select date '2026-01-01' as event_date_utc, 'USD' as currency_code, "
        "5 as transaction_count, 100.0 as amount_native_total, "
        "90.0 as amount_eur_total, 'ok' as fx_status, false as is_carried_forward"
    )
    con.execute(
        "create table data_quality_daily as "
        "select date '2026-01-01' as ingestion_date, 5 as received_row_count, "
        "0 as quarantined_row_count, 0 as duplicate_removed_count, "
        "0 as late_row_count, 0.0 as rejection_rate, 0.0 as late_rate, "
        "0 as quarantined_missing_key_count, 0 as quarantined_missing_currency_count, "
        "0 as quarantined_unknown_currency_count, "
        "0 as quarantined_non_positive_amount_count, "
        "0 as quarantined_invalid_amount_count, "
        "0 as quarantined_invalid_timestamp_count"
    )
    con.execute(
        "create table dim_country as "
        "select 'FR' as alpha_2, 'FRA' as alpha_3, 'France' as country_name"
    )
    con.execute(
        "create table dim_currency as "
        "select 'USD' as currency_code, 'US Dollar' as currency_name, 2 as minor_units"
    )
    con.close()


def _run_app(serving_path: str) -> AppTest:
    sys.argv = ["app.py", "--serving-path", serving_path]
    app = AppTest.from_file(_APP_PATH, default_timeout=60)
    app.run()
    return app


def test_app_runs_without_exception_on_a_valid_serving_file(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    _build_serving(serving_path)

    app = _run_app(str(serving_path))

    assert len(app.exception) == 0


def test_app_renders_the_expected_title(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    _build_serving(serving_path)

    app = _run_app(str(serving_path))

    assert [t.value for t in app.title] == ["Payments dashboard"]


def test_each_of_the_four_views_renders_at_least_one_element(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    _build_serving(serving_path)

    app = _run_app(str(serving_path))

    assert len(app.tabs) == 4
    for tab in app.tabs:
        assert len(tab.get("dataframe")) + len(tab.get("metric")) > 0


def test_app_shows_a_readable_error_when_the_serving_file_is_missing(tmp_path) -> None:
    missing_path = tmp_path / "does-not-exist.duckdb"

    app = _run_app(str(missing_path))

    assert len(app.exception) == 0
    assert len(app.error) == 1
    assert str(missing_path) in app.error[0].value
