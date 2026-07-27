"""Cache-first orchestration for fetching exchange rates."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from payments.fx import calendar
from payments.fx.cache import FxRateRow, create_schema, fetch_cached_rows, upsert_rows
from payments.fx.client import ExchangeRates, FxPermanentError, FxTransientError, fetch_rates

BASE_CURRENCY = "EUR"
DEFAULT_QUOTE_CURRENCIES = ("USD", "GBP", "CHF", "SEK", "PLN", "JPY", "CAD", "MAD")


@dataclass(frozen=True)
class FetchFxResult:
    rows: list[FxRateRow]
    network_calls: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _row_from_classification(
    requested_date: date,
    symbol: str,
    base: str,
    classification: calendar.FxStatusResult,
    fetched_at: datetime,
) -> FxRateRow:
    return FxRateRow(
        rate_date=requested_date,
        quote_currency=symbol,
        base_currency=base,
        rate=classification.rate,
        effective_rate_date=classification.effective_rate_date,
        is_carried_forward=classification.is_carried_forward,
        fx_status=classification.fx_status,
        unavailable_reason=classification.unavailable_reason,
        fetched_at=fetched_at,
    )


def _needs_fetch(key: tuple[date, str], cached: dict[tuple[date, str], FxRateRow]) -> bool:
    if key not in cached:
        return True
    return not calendar.is_final(cached[key].unavailable_reason)


def fetch_fx_rates(
    db_path: str | Path,
    *,
    dates: Sequence[date],
    symbols: Sequence[str],
    base: str,
    fetch: Callable[..., ExchangeRates] = fetch_rates,
    now: Callable[[], datetime] = _utc_now,
) -> FetchFxResult:
    path = str(db_path)
    keys = [(requested_date, symbol) for requested_date in dates for symbol in symbols]

    con = duckdb.connect(path)
    create_schema(con)
    cached = fetch_cached_rows(con, keys)
    con.close()

    missing_dates = [
        requested_date
        for requested_date in dates
        if any(_needs_fetch((requested_date, symbol), cached) for symbol in symbols)
    ]

    network_calls = 0
    new_rows: list[FxRateRow] = []
    for requested_date in missing_dates:
        fetched_at = now()
        try:
            network_calls += 1
            result = fetch(requested_date.isoformat(), base=base, symbols=symbols)
        except FxPermanentError:
            classification = calendar.permanent_error_result()
            for symbol in symbols:
                new_rows.append(
                    _row_from_classification(
                        requested_date, symbol, base, classification, fetched_at
                    )
                )
            continue
        except FxTransientError:
            classification = calendar.transient_error_result()
            for symbol in symbols:
                new_rows.append(
                    _row_from_classification(
                        requested_date, symbol, base, classification, fetched_at
                    )
                )
            continue

        effective_date = date.fromisoformat(result.effective_date)
        for symbol in symbols:
            rate = result.rates.get(symbol)
            classification = calendar.classify(requested_date, effective_date, rate)
            new_rows.append(
                _row_from_classification(requested_date, symbol, base, classification, fetched_at)
            )

    if new_rows:
        con = duckdb.connect(path)
        upsert_rows(con, new_rows)
        con.close()

    con = duckdb.connect(path)
    all_cached = fetch_cached_rows(con, keys)
    con.close()
    return FetchFxResult(
        rows=[all_cached[key] for key in keys],
        network_calls=network_calls,
    )
