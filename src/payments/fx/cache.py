"""DuckDB-backed cache for exchange rates, keyed by requested date and currency."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

import duckdb

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fx_rates (
    rate_date DATE NOT NULL,
    quote_currency VARCHAR NOT NULL,
    base_currency VARCHAR NOT NULL,
    rate DOUBLE,
    effective_rate_date DATE,
    is_carried_forward BOOLEAN NOT NULL,
    fx_status VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (rate_date, quote_currency)
)
"""

_UPSERT_SQL = """
INSERT INTO fx_rates (
    rate_date, quote_currency, base_currency, rate, effective_rate_date,
    is_carried_forward, fx_status, fetched_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (rate_date, quote_currency) DO UPDATE SET
    base_currency = excluded.base_currency,
    rate = excluded.rate,
    effective_rate_date = excluded.effective_rate_date,
    is_carried_forward = excluded.is_carried_forward,
    fx_status = excluded.fx_status,
    fetched_at = excluded.fetched_at
"""


@dataclass(frozen=True)
class FxRateRow:
    rate_date: date
    quote_currency: str
    base_currency: str
    rate: float | None
    effective_rate_date: date | None
    is_carried_forward: bool
    fx_status: str
    fetched_at: datetime


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_CREATE_TABLE_SQL)


def upsert_rows(con: duckdb.DuckDBPyConnection, rows: Sequence[FxRateRow]) -> None:
    if not rows:
        return
    con.execute("BEGIN TRANSACTION")
    try:
        for row in rows:
            con.execute(
                _UPSERT_SQL,
                [
                    row.rate_date,
                    row.quote_currency,
                    row.base_currency,
                    row.rate,
                    row.effective_rate_date,
                    row.is_carried_forward,
                    row.fx_status,
                    row.fetched_at,
                ],
            )
    except Exception:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def fetch_cached_rows(
    con: duckdb.DuckDBPyConnection, keys: Sequence[tuple[date, str]]
) -> dict[tuple[date, str], FxRateRow]:
    if not keys:
        return {}

    requested_dates = sorted({key[0] for key in keys})
    placeholders = ", ".join("?" for _ in requested_dates)
    rows = con.execute(
        f"""
        SELECT rate_date, quote_currency, base_currency, rate, effective_rate_date,
               is_carried_forward, fx_status, fetched_at
        FROM fx_rates
        WHERE rate_date IN ({placeholders})
        """,
        requested_dates,
    ).fetchall()

    by_key = {
        (row[0], row[1]): FxRateRow(
            rate_date=row[0],
            quote_currency=row[1],
            base_currency=row[2],
            rate=row[3],
            effective_rate_date=row[4],
            is_carried_forward=row[5],
            fx_status=row[6],
            fetched_at=row[7],
        )
        for row in rows
    }
    return {key: by_key[key] for key in keys if key in by_key}
