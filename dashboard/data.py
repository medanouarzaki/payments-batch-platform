"""Read-only, cache-invalidated access to the serving file for the dashboard."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st


def serving_mtime_ns(path: str) -> int:
    """Return the serving file's modification time in nanoseconds.

    Raises FileNotFoundError with a clear message if the file is absent.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"serving file not found: {target}")
    return target.stat().st_mtime_ns


# mtime_ns is threaded through every cached function below purely to key the
# cache. It is never read in the body. Without it, a cached connection or
# frame would stay keyed to the old inode after the serving file is replaced
# atomically (os.replace), so the dashboard would keep serving stale data
# forever instead of refreshing or raising an error.


# DuckDB shares the underlying database instance across connections opened on
# the same path within one process: opening a fresh connection after the file
# has been replaced still returns the old content if a prior connection to
# that same path is still open. So the previous connection for a given path
# must be closed before a new one is opened, or the mtime_ns cache key alone
# does not actually make the dashboard see fresh data.
_open_connections: dict[str, tuple[int, duckdb.DuckDBPyConnection]] = {}


@st.cache_resource
def _connection(serving_path: str, mtime_ns: int) -> duckdb.DuckDBPyConnection:
    previous = _open_connections.get(serving_path)
    if previous is not None and previous[0] != mtime_ns:
        previous[1].close()
    con = duckdb.connect(serving_path, read_only=True)
    _open_connections[serving_path] = (mtime_ns, con)
    return con


@st.cache_data
def load_daily_volumes(serving_path: str, mtime_ns: int) -> pd.DataFrame:
    con = _connection(serving_path, mtime_ns)
    return con.execute(
        "select event_date_utc, debtor_country, "
        "sum(transaction_count) as transaction_count, "
        "sum(amount_eur_total) as amount_eur_total "
        "from agg_transactions_daily "
        "group by 1, 2"
    ).df()


@st.cache_data
def load_channel_rejections(serving_path: str, mtime_ns: int) -> pd.DataFrame:
    con = _connection(serving_path, mtime_ns)
    return con.execute(
        "select event_date_utc, channel, status, transaction_count, "
        "amount_eur_total from agg_transactions_channel_daily"
    ).df()


@st.cache_data
def load_fx_exposure(serving_path: str, mtime_ns: int) -> pd.DataFrame:
    con = _connection(serving_path, mtime_ns)
    return con.execute(
        "select event_date_utc, currency_code, transaction_count, "
        "amount_native_total, amount_eur_total, fx_status, is_carried_forward "
        "from agg_fx_exposure_daily"
    ).df()


@st.cache_data
def load_data_quality(serving_path: str, mtime_ns: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (quality, degraded), two frames on two different date axes.

    quality is keyed by ingestion_date, from data_quality_daily. degraded is
    keyed by event_date_utc, from agg_fx_exposure_daily: one row per day
    where at least one row used a carried-forward exchange rate, or at least
    one row has no rate at all (fx_status = 'rate_missing'). The two axes are
    not the same and are never joined here.
    """
    con = _connection(serving_path, mtime_ns)
    quality = con.execute(
        "select ingestion_date, received_row_count, quarantined_row_count, "
        "duplicate_removed_count, late_row_count, rejection_rate, late_rate, "
        "quarantined_missing_key_count, quarantined_missing_currency_count, "
        "quarantined_unknown_currency_count, quarantined_non_positive_amount_count, "
        "quarantined_invalid_amount_count, quarantined_invalid_timestamp_count "
        "from data_quality_daily"
    ).df()
    degraded = con.execute(
        "select event_date_utc, "
        "sum(case when is_carried_forward then 1 else 0 end) as carried_forward_rows, "
        "sum(case when fx_status = 'rate_missing' then 1 else 0 end) as rate_missing_rows "
        "from agg_fx_exposure_daily "
        "group by 1 "
        "having sum(case when is_carried_forward then 1 else 0 end) > 0 "
        "or sum(case when fx_status = 'rate_missing' then 1 else 0 end) > 0 "
        "order by 1"
    ).df()
    return quality, degraded


@st.cache_data
def load_countries(serving_path: str, mtime_ns: int) -> pd.DataFrame:
    con = _connection(serving_path, mtime_ns)
    return con.execute("select alpha_2, alpha_3, country_name from dim_country").df()


@st.cache_data
def load_currencies(serving_path: str, mtime_ns: int) -> pd.DataFrame:
    con = _connection(serving_path, mtime_ns)
    return con.execute("select currency_code, currency_name, minor_units from dim_currency").df()
