"""Cache-first orchestration for fetching exchange rates."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path

import duckdb

from payments.fx import calendar
from payments.fx.cache import FxRateRow, create_schema, fetch_cached_rows, upsert_rows
from payments.fx.client import ExchangeRates, FxClientError, fetch_rates


def fetch_fx_rates(
    db_path: str | Path,
    *,
    dates: Sequence[date],
    symbols: Sequence[str],
    base: str,
    fetch: Callable[..., ExchangeRates] = fetch_rates,
    now: Callable[[], datetime] = datetime.utcnow,
) -> list[FxRateRow]:
    path = str(db_path)
    keys = [(requested_date, symbol) for requested_date in dates for symbol in symbols]

    con = duckdb.connect(path)
    create_schema(con)
    cached = fetch_cached_rows(con, keys)
    con.close()

    missing_dates = [
        requested_date
        for requested_date in dates
        if any((requested_date, symbol) not in cached for symbol in symbols)
    ]

    new_rows: list[FxRateRow] = []
    for requested_date in missing_dates:
        fetched_at = now()
        try:
            result = fetch(requested_date.isoformat(), base=base, symbols=symbols)
        except FxClientError:
            for symbol in symbols:
                classification = calendar.classify(requested_date, None, None)
                new_rows.append(
                    FxRateRow(
                        rate_date=requested_date,
                        quote_currency=symbol,
                        base_currency=base,
                        rate=classification.rate,
                        effective_rate_date=classification.effective_rate_date,
                        is_carried_forward=classification.is_carried_forward,
                        fx_status=classification.fx_status,
                        fetched_at=fetched_at,
                    )
                )
            continue

        effective_date = date.fromisoformat(result.effective_date)
        for symbol in symbols:
            rate = result.rates.get(symbol)
            classification = calendar.classify(requested_date, effective_date, rate)
            new_rows.append(
                FxRateRow(
                    rate_date=requested_date,
                    quote_currency=symbol,
                    base_currency=base,
                    rate=classification.rate,
                    effective_rate_date=classification.effective_rate_date,
                    is_carried_forward=classification.is_carried_forward,
                    fx_status=classification.fx_status,
                    fetched_at=fetched_at,
                )
            )

    if new_rows:
        con = duckdb.connect(path)
        upsert_rows(con, new_rows)
        con.close()

    con = duckdb.connect(path)
    all_cached = fetch_cached_rows(con, keys)
    con.close()
    return [all_cached[key] for key in keys]
