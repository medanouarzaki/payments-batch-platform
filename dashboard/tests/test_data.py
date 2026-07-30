"""Behavior of the dashboard data layer: caching key, read-only access, isolation."""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

_DATA_PATH = Path(__file__).resolve().parents[1] / "data.py"
_SPEC = importlib.util.spec_from_file_location("dashboard_data", _DATA_PATH)
data = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(data)


def _build_serving(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        "create table agg_transactions_daily ("
        "event_date_utc date, debtor_country varchar, status varchar, "
        "transaction_count integer, amount_eur_total decimal(38,2))"
    )
    con.execute(
        "insert into agg_transactions_daily values "
        "(date '2026-01-01', 'FR', 'ACCEPTED', 10, 100.50), "
        "(date '2026-01-01', 'DE', 'ACCEPTED', 5, 50.25), "
        "(date '2026-01-02', 'FR', 'REJECTED', 3, 30.00)"
    )
    con.close()


def test_load_daily_volumes_returns_one_row_per_date_and_country(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    _build_serving(serving_path)

    frame = data.load_daily_volumes(str(serving_path), data.serving_mtime_ns(str(serving_path)))

    keys = list(zip(frame["event_date_utc"], frame["debtor_country"], strict=True))
    assert len(frame) == 3
    assert len(set(keys)) == 3


def test_load_daily_volumes_converts_amounts_to_float(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    _build_serving(serving_path)

    frame = data.load_daily_volumes(str(serving_path), data.serving_mtime_ns(str(serving_path)))

    assert frame["amount_eur_total"].dtype == "float64"
    assert frame["amount_eur_total"].sum() == pytest.approx(180.75)


def test_cache_key_changes_when_the_serving_file_is_replaced(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    replacement_path = tmp_path / "replacement.duckdb"
    _build_serving(serving_path)

    first_mtime = data.serving_mtime_ns(str(serving_path))
    first_frame = data.load_daily_volumes(str(serving_path), first_mtime)
    first_total = first_frame["transaction_count"].sum()

    con = duckdb.connect(str(replacement_path))
    con.execute(
        "create table agg_transactions_daily ("
        "event_date_utc date, debtor_country varchar, status varchar, "
        "transaction_count integer, amount_eur_total decimal(38,2))"
    )
    con.execute(
        "insert into agg_transactions_daily values "
        "(date '2026-02-01', 'IT', 'ACCEPTED', 999, 9999.99)"
    )
    con.close()
    os.replace(replacement_path, serving_path)

    second_mtime = data.serving_mtime_ns(str(serving_path))
    assert first_mtime != second_mtime, "cache key did not change after the file was replaced"

    second_frame = data.load_daily_volumes(str(serving_path), second_mtime)
    second_total = second_frame["transaction_count"].sum()

    assert second_total == 999, (
        f"second read returned {second_total}, the stale first-file total was {first_total}"
    )
    assert set(second_frame["debtor_country"]) == {"IT"}


def test_connection_is_read_only(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    _build_serving(serving_path)

    con = data._connection(str(serving_path), data.serving_mtime_ns(str(serving_path)))

    with pytest.raises(duckdb.Error):
        con.execute("create table not_allowed (a integer)")


def test_loaders_do_not_import_the_payments_package() -> None:
    assert not any(name.startswith("payments") for name in sys.modules)


def test_a_missing_serving_file_raises_a_clear_error(tmp_path) -> None:
    missing_path = tmp_path / "absent.duckdb"

    with pytest.raises(FileNotFoundError, match="serving file not found"):
        data.serving_mtime_ns(str(missing_path))


def test_load_data_quality_keeps_zero_count_reasons(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    con = duckdb.connect(str(serving_path))
    con.execute(
        "create table data_quality_daily ("
        "ingestion_date date, received_row_count integer, "
        "quarantined_row_count integer, duplicate_removed_count integer, "
        "late_row_count integer, rejection_rate double, late_rate double, "
        "quarantined_missing_key_count integer, "
        "quarantined_missing_currency_count integer, "
        "quarantined_unknown_currency_count integer, "
        "quarantined_non_positive_amount_count integer, "
        "quarantined_invalid_amount_count integer, "
        "quarantined_invalid_timestamp_count integer)"
    )
    con.execute(
        "insert into data_quality_daily values "
        "(date '2026-01-01', 100, 5, 1, 2, 0.05, 0.03, 5, 0, 0, 0, 0, 0), "
        "(date '2026-01-02', 200, 3, 0, 1, 0.015, 0.005, 3, 0, 0, 0, 0, 0)"
    )
    con.execute(
        "create table agg_fx_exposure_daily ("
        "event_date_utc date, currency_code varchar, transaction_count integer, "
        "amount_native_total decimal(38,2), amount_eur_total decimal(38,2), "
        "fx_status varchar, is_carried_forward boolean)"
    )
    con.close()

    quality, degraded = data.load_data_quality(
        str(serving_path), data.serving_mtime_ns(str(serving_path))
    )

    assert len(quality) == 2
    assert len(degraded) == 0
    assert quality["ingestion_date"].nunique() == 2
    assert "quarantined_invalid_timestamp_count" in quality.columns
    assert quality["quarantined_invalid_timestamp_count"].sum() == 0
    assert "quarantined_missing_currency_count" in quality.columns
    assert quality["quarantined_missing_currency_count"].sum() == 0


def test_load_fx_exposure_keeps_the_carried_forward_flag(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    con = duckdb.connect(str(serving_path))
    con.execute(
        "create table agg_fx_exposure_daily ("
        "event_date_utc date, currency_code varchar, transaction_count integer, "
        "amount_native_total decimal(38,2), amount_eur_total decimal(38,2), "
        "fx_status varchar, is_carried_forward boolean)"
    )
    con.execute(
        "insert into agg_fx_exposure_daily values "
        "(date '2026-01-01', 'USD', 10, 100.0, 90.0, 'ok', false), "
        "(date '2026-01-01', 'GBP', 4, 40.0, 45.0, 'carried_forward', true)"
    )
    con.close()

    frame = data.load_fx_exposure(str(serving_path), data.serving_mtime_ns(str(serving_path)))

    assert "is_carried_forward" in frame.columns
    flags = dict(zip(frame["currency_code"], frame["is_carried_forward"], strict=True))
    assert flags == {"USD": False, "GBP": True}


def test_load_data_quality_identifies_degraded_days(tmp_path) -> None:
    serving_path = tmp_path / "marts.duckdb"
    con = duckdb.connect(str(serving_path))
    con.execute(
        "create table data_quality_daily ("
        "ingestion_date date, received_row_count integer, "
        "quarantined_row_count integer, duplicate_removed_count integer, "
        "late_row_count integer, rejection_rate double, late_rate double, "
        "quarantined_missing_key_count integer, "
        "quarantined_missing_currency_count integer, "
        "quarantined_unknown_currency_count integer, "
        "quarantined_non_positive_amount_count integer, "
        "quarantined_invalid_amount_count integer, "
        "quarantined_invalid_timestamp_count integer)"
    )
    con.execute(
        "insert into data_quality_daily values "
        "(date '2026-01-01', 100, 0, 0, 0, 0.0, 0.0, 0, 0, 0, 0, 0, 0)"
    )
    con.execute(
        "create table agg_fx_exposure_daily ("
        "event_date_utc date, currency_code varchar, transaction_count integer, "
        "amount_native_total decimal(38,2), amount_eur_total decimal(38,2), "
        "fx_status varchar, is_carried_forward boolean)"
    )
    con.execute(
        "insert into agg_fx_exposure_daily values "
        "(date '2026-02-01', 'USD', 10, 100.0, 90.0, 'ok', false), "
        "(date '2026-02-02', 'GBP', 4, 40.0, 45.0, 'carried_forward', true), "
        "(date '2026-02-03', 'JPY', 2, 20.0, NULL, 'rate_missing', false)"
    )
    con.close()

    mtime_ns = data.serving_mtime_ns(str(serving_path))
    _, degraded = data.load_data_quality(str(serving_path), mtime_ns)

    degraded_dates = set(degraded["event_date_utc"].dt.date)
    assert degraded_dates == {date(2026, 2, 2), date(2026, 2, 3)}
