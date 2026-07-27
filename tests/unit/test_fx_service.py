from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import UTC, date, datetime

import duckdb

from payments.fx.cache import FxRateRow, create_schema, upsert_rows
from payments.fx.client import ExchangeRates, FxPermanentError, FxTransientError
from payments.fx.service import fetch_fx_rates

_FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _fixed_now() -> datetime:
    return _FIXED_NOW


class _StubClient:
    def __init__(self, responses_by_date: dict[str, ExchangeRates | Exception]):
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []
        self._responses_by_date = responses_by_date

    def __call__(self, requested_date: str, *, base: str, symbols) -> ExchangeRates:
        self.calls.append((requested_date, base, tuple(symbols)))
        outcome = self._responses_by_date[requested_date]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FailingIfCalledClient:
    def __call__(self, requested_date: str, *, base: str, symbols) -> ExchangeRates:
        raise AssertionError(f"network should not have been called for {requested_date}")


def _seed_cache(db_path, rows):
    con = duckdb.connect(str(db_path))
    create_schema(con)
    upsert_rows(con, rows)
    con.close()


def test_fully_cached_request_makes_no_network_calls(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 6, 1)
    _seed_cache(
        db_path,
        [
            FxRateRow(
                rate_date=requested,
                quote_currency="USD",
                base_currency="EUR",
                rate=1.1646,
                effective_rate_date=requested,
                is_carried_forward=False,
                fx_status="ok",
                unavailable_reason=None,
                fetched_at=_FIXED_NOW,
            )
        ],
    )
    result = fetch_fx_rates(
        db_path,
        dates=[requested],
        symbols=["USD"],
        base="EUR",
        fetch=_FailingIfCalledClient(),
        now=_fixed_now,
    )
    assert result[0].rate == 1.1646


def test_partially_cached_request_only_calls_network_for_missing_dates(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    cached_date = date(2026, 6, 1)
    missing_date = date(2026, 6, 2)
    _seed_cache(
        db_path,
        [
            FxRateRow(
                rate_date=cached_date,
                quote_currency="USD",
                base_currency="EUR",
                rate=1.1646,
                effective_rate_date=cached_date,
                is_carried_forward=False,
                fx_status="ok",
                unavailable_reason=None,
                fetched_at=_FIXED_NOW,
            )
        ],
    )
    client = _StubClient(
        {
            "2026-06-02": ExchangeRates(
                requested_date="2026-06-02",
                effective_date="2026-06-02",
                base_currency="EUR",
                rates={"USD": 1.17},
            )
        }
    )
    fetch_fx_rates(
        db_path,
        dates=[cached_date, missing_date],
        symbols=["USD"],
        base="EUR",
        fetch=client,
        now=_fixed_now,
    )
    assert client.calls == [("2026-06-02", "EUR", ("USD",))]


def test_second_pass_over_same_dates_and_symbols_makes_no_additional_calls(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 6, 1)
    client = _StubClient(
        {
            "2026-06-01": ExchangeRates(
                requested_date="2026-06-01",
                effective_date="2026-06-01",
                base_currency="EUR",
                rates={"USD": 1.1646, "GBP": 0.86493},
            )
        }
    )
    fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD", "GBP"], base="EUR", fetch=client, now=_fixed_now
    )
    calls_after_first = len(client.calls)
    fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD", "GBP"], base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == calls_after_first == 1


def test_second_pass_over_five_dates_and_eight_currencies_makes_no_additional_calls(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    dates_list = [date(2026, 6, day) for day in range(1, 6)]
    symbols = ["USD", "GBP", "CHF", "SEK", "PLN", "JPY", "CAD", "MAD"]
    client = _StubClient(
        {
            requested_date.isoformat(): ExchangeRates(
                requested_date=requested_date.isoformat(),
                effective_date=requested_date.isoformat(),
                base_currency="EUR",
                rates=dict.fromkeys(symbols, 1.0),
            )
            for requested_date in dates_list
        }
    )
    fetch_fx_rates(
        db_path, dates=dates_list, symbols=symbols, base="EUR", fetch=client, now=_fixed_now
    )
    calls_after_first = len(client.calls)
    fetch_fx_rates(
        db_path, dates=dates_list, symbols=symbols, base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == calls_after_first == 5


def test_permanent_error_on_one_date_degrades_and_continues(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    bad_date = date(2026, 6, 1)
    good_date = date(2026, 6, 2)
    client = _StubClient(
        {
            "2026-06-01": FxPermanentError("not found"),
            "2026-06-02": ExchangeRates(
                requested_date="2026-06-02",
                effective_date="2026-06-02",
                base_currency="EUR",
                rates={"USD": 1.17},
            ),
        }
    )
    result = fetch_fx_rates(
        db_path,
        dates=[bad_date, good_date],
        symbols=["USD"],
        base="EUR",
        fetch=client,
        now=_fixed_now,
    )
    by_date = {row.rate_date: row for row in result}
    assert by_date[bad_date].fx_status == "unavailable"
    assert by_date[bad_date].rate is None
    assert by_date[bad_date].unavailable_reason == "no_data_for_date"
    assert by_date[good_date].fx_status == "ok"
    assert by_date[good_date].rate == 1.17
    assert len(client.calls) == 2


def test_transient_error_on_one_date_degrades_and_continues(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    bad_date = date(2026, 6, 1)
    good_date = date(2026, 6, 2)
    client = _StubClient(
        {
            "2026-06-01": FxTransientError("exhausted retries"),
            "2026-06-02": ExchangeRates(
                requested_date="2026-06-02",
                effective_date="2026-06-02",
                base_currency="EUR",
                rates={"USD": 1.17},
            ),
        }
    )
    result = fetch_fx_rates(
        db_path,
        dates=[bad_date, good_date],
        symbols=["USD"],
        base="EUR",
        fetch=client,
        now=_fixed_now,
    )
    by_date = {row.rate_date: row for row in result}
    assert by_date[bad_date].fx_status == "unavailable"
    assert by_date[bad_date].rate is None
    assert by_date[bad_date].unavailable_reason == "fetch_failed"
    assert by_date[good_date].fx_status == "ok"


def test_transient_failure_then_success_is_retried_on_second_pass(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 6, 1)
    client = _StubClient({"2026-06-01": FxTransientError("exhausted retries")})

    first = fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert first[0].fx_status == "unavailable"
    assert first[0].unavailable_reason == "fetch_failed"
    assert len(client.calls) == 1

    client._responses_by_date["2026-06-01"] = ExchangeRates(
        requested_date="2026-06-01",
        effective_date="2026-06-01",
        base_currency="EUR",
        rates={"USD": 1.1646},
    )
    second = fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == 2
    assert second[0].fx_status == "ok"
    assert second[0].rate == 1.1646


def test_permanent_error_is_not_retried_on_second_pass(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 6, 1)
    client = _StubClient({"2026-06-01": FxPermanentError("not found")})

    fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == 1

    second = fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == 1
    assert second[0].fx_status == "unavailable"
    assert second[0].unavailable_reason == "no_data_for_date"


def test_absent_currency_is_not_retried_on_second_pass(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 6, 1)
    client = _StubClient(
        {
            "2026-06-01": ExchangeRates(
                requested_date="2026-06-01",
                effective_date="2026-06-01",
                base_currency="EUR",
                rates={"USD": 1.1646},
            )
        }
    )

    fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD", "MAD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == 1

    second = fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD", "MAD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == 1
    by_currency = {row.quote_currency: row for row in second}
    assert by_currency["MAD"].unavailable_reason == "currency_not_published"


def test_rate_too_old_is_not_retried_on_second_pass(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 6, 10)
    client = _StubClient(
        {
            "2026-06-10": ExchangeRates(
                requested_date="2026-06-10",
                effective_date="2026-05-01",
                base_currency="EUR",
                rates={"USD": 1.16},
            )
        }
    )

    fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == 1

    second = fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert len(client.calls) == 1
    assert second[0].unavailable_reason == "rate_too_old"


def test_carried_forward_row_is_stored_under_requested_date(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 5, 30)
    client = _StubClient(
        {
            "2026-05-30": ExchangeRates(
                requested_date="2026-05-30",
                effective_date="2026-05-29",
                base_currency="EUR",
                rates={"USD": 1.1644},
            )
        }
    )
    result = fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert result[0].rate_date == requested
    assert result[0].effective_rate_date == date(2026, 5, 29)
    assert result[0].fx_status == "carried_forward"
    assert result[0].is_carried_forward is True


def test_absent_currency_produces_unavailable_row(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 6, 1)
    client = _StubClient(
        {
            "2026-06-01": ExchangeRates(
                requested_date="2026-06-01",
                effective_date="2026-06-01",
                base_currency="EUR",
                rates={"USD": 1.1646},
            )
        }
    )
    result = fetch_fx_rates(
        db_path,
        dates=[requested],
        symbols=["USD", "MAD"],
        base="EUR",
        fetch=client,
        now=_fixed_now,
    )
    by_currency = {row.quote_currency: row for row in result}
    assert by_currency["MAD"].fx_status == "unavailable"
    assert by_currency["MAD"].rate is None
    assert by_currency["MAD"].effective_rate_date is None
    assert by_currency["MAD"].unavailable_reason == "currency_not_published"


def test_all_three_statuses_are_reachable_and_no_others_appear(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    ok_date = date(2026, 6, 1)
    carried_date = date(2026, 5, 30)
    stale_date = date(2026, 6, 10)
    client = _StubClient(
        {
            "2026-06-01": ExchangeRates(
                requested_date="2026-06-01",
                effective_date="2026-06-01",
                base_currency="EUR",
                rates={"USD": 1.1646, "MAD": 10.69},
            ),
            "2026-05-30": ExchangeRates(
                requested_date="2026-05-30",
                effective_date="2026-05-29",
                base_currency="EUR",
                rates={"USD": 1.1644, "MAD": 10.68},
            ),
            "2026-06-10": ExchangeRates(
                requested_date="2026-06-10",
                effective_date="2026-05-01",
                base_currency="EUR",
                rates={"USD": 1.16, "MAD": 10.7},
            ),
        }
    )
    result = fetch_fx_rates(
        db_path,
        dates=[ok_date, carried_date, stale_date],
        symbols=["USD", "MAD"],
        base="EUR",
        fetch=client,
        now=_fixed_now,
    )
    statuses = {row.fx_status for row in result}
    assert statuses == {"ok", "carried_forward", "unavailable"}


def _second_connection_probe_script(db_path: str) -> str:
    return textwrap.dedent(
        f"""
        import duckdb
        con = duckdb.connect({db_path!r})
        con.execute("create table if not exists probe (a integer)")
        con.execute("insert into probe values (1)")
        con.close()
        """
    )


def test_no_connection_is_held_during_the_network_call(tmp_path):
    db_path = tmp_path / "cache.duckdb"
    requested = date(2026, 6, 1)

    def client(requested_date: str, *, base: str, symbols) -> ExchangeRates:
        probe = subprocess.run(
            [sys.executable, "-c", _second_connection_probe_script(str(db_path))],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert probe.returncode == 0, probe.stderr
        return ExchangeRates(
            requested_date=requested_date,
            effective_date=requested_date,
            base_currency=base,
            rates={symbol: 1.0 for symbol in symbols},
        )

    result = fetch_fx_rates(
        db_path, dates=[requested], symbols=["USD"], base="EUR", fetch=client, now=_fixed_now
    )
    assert result[0].fx_status == "ok"
