from __future__ import annotations

from datetime import UTC, date, datetime

import duckdb

from payments.fx.cache import FxRateRow, create_schema, fetch_cached_rows, upsert_rows

_FETCHED_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _row(
    rate_date: date,
    currency: str,
    rate: float | None,
    effective: date | None = None,
    carried: bool = False,
    status: str = "ok",
    reason: str | None = None,
    fetched_at: datetime = _FETCHED_AT,
) -> FxRateRow:
    return FxRateRow(
        rate_date=rate_date,
        quote_currency=currency,
        base_currency="EUR",
        rate=rate,
        effective_rate_date=effective,
        is_carried_forward=carried,
        fx_status=status,
        unavailable_reason=reason,
        fetched_at=fetched_at,
    )


def test_create_schema_is_idempotent(tmp_path):
    con = duckdb.connect(str(tmp_path / "cache.duckdb"))
    create_schema(con)
    create_schema(con)
    upsert_rows(con, [_row(date(2026, 6, 1), "USD", 1.1646, effective=date(2026, 6, 1))])
    create_schema(con)
    count = con.execute("select count(*) from fx_rates").fetchone()[0]
    assert count == 1
    con.close()


def test_upsert_same_key_twice_does_not_duplicate(tmp_path):
    con = duckdb.connect(str(tmp_path / "cache.duckdb"))
    create_schema(con)
    upsert_rows(con, [_row(date(2026, 6, 1), "USD", 1.1646, effective=date(2026, 6, 1))])
    upsert_rows(con, [_row(date(2026, 6, 1), "USD", 1.9999, effective=date(2026, 6, 1))])
    rows = con.execute(
        "select rate from fx_rates where rate_date = ? and quote_currency = ?",
        [date(2026, 6, 1), "USD"],
    ).fetchall()
    assert rows == [(1.9999,)]
    con.close()


def test_row_is_stored_under_requested_date_not_effective_date(tmp_path):
    con = duckdb.connect(str(tmp_path / "cache.duckdb"))
    create_schema(con)
    requested = date(2026, 5, 30)
    effective = date(2026, 5, 29)
    upsert_rows(
        con,
        [
            _row(
                requested,
                "USD",
                1.1644,
                effective=effective,
                carried=True,
                status="carried_forward",
            )
        ],
    )
    cached = fetch_cached_rows(con, [(requested, "USD")])
    assert cached[(requested, "USD")].rate_date == requested
    assert cached[(requested, "USD")].effective_rate_date == effective
    assert (effective, "USD") not in fetch_cached_rows(con, [(effective, "USD")])
    con.close()


def test_absent_currency_is_cached_as_unavailable(tmp_path):
    con = duckdb.connect(str(tmp_path / "cache.duckdb"))
    create_schema(con)
    requested = date(2026, 6, 1)
    upsert_rows(
        con,
        [
            _row(
                requested,
                "MAD",
                None,
                effective=None,
                status="unavailable",
                reason="currency_not_published",
            )
        ],
    )
    cached = fetch_cached_rows(con, [(requested, "MAD")])
    assert cached[(requested, "MAD")].fx_status == "unavailable"
    assert cached[(requested, "MAD")].rate is None
    assert cached[(requested, "MAD")].effective_rate_date is None
    assert cached[(requested, "MAD")].unavailable_reason == "currency_not_published"
    con.close()


def test_unavailable_reason_is_null_when_status_is_ok_or_carried_forward(tmp_path):
    con = duckdb.connect(str(tmp_path / "cache.duckdb"))
    create_schema(con)
    ok_date = date(2026, 6, 1)
    carried_date = date(2026, 5, 30)
    upsert_rows(
        con,
        [
            _row(ok_date, "USD", 1.1646, effective=ok_date, status="ok"),
            _row(
                carried_date,
                "USD",
                1.1644,
                effective=date(2026, 5, 29),
                carried=True,
                status="carried_forward",
            ),
        ],
    )
    cached = fetch_cached_rows(con, [(ok_date, "USD"), (carried_date, "USD")])
    assert cached[(ok_date, "USD")].unavailable_reason is None
    assert cached[(carried_date, "USD")].unavailable_reason is None
    con.close()


def test_fetched_at_round_trips_as_a_comparable_aware_instant(tmp_path):
    con = duckdb.connect(str(tmp_path / "cache.duckdb"))
    create_schema(con)
    written_at = datetime(2026, 6, 1, 9, 30, 0, tzinfo=UTC)
    requested = date(2026, 6, 1)
    upsert_rows(con, [_row(requested, "USD", 1.1646, effective=requested, fetched_at=written_at)])
    cached = fetch_cached_rows(con, [(requested, "USD")])
    read_back = cached[(requested, "USD")].fetched_at
    assert read_back.tzinfo is not None
    assert read_back == written_at
    con.close()
