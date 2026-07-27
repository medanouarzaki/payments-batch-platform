from __future__ import annotations

import random as random_module
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from payments.fx.client import (
    ExchangeRates,
    FxPermanentError,
    FxTransientError,
    _jittered_delay,
    fetch_rates,
)

FAKE_BASE_URL = "https://fx.test/v1"


@pytest.fixture(autouse=True)
def _fx_base_url(monkeypatch):
    monkeypatch.setenv("PAYMENTS_FX_API_BASE_URL", FAKE_BASE_URL)


def _no_sleep(seconds: float) -> None:
    pass


@responses.activate
def test_nominal_call_returns_structured_result():
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-06-01",
        json={"amount": 1.0, "base": "EUR", "date": "2026-06-01", "rates": {"USD": 1.1646}},
        status=200,
    )
    result = fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert result == ExchangeRates(
        requested_date="2026-06-01",
        effective_date="2026-06-01",
        base_currency="EUR",
        rates={"USD": 1.1646},
    )
    assert len(responses.calls) == 1


@responses.activate
def test_saturday_reports_both_requested_and_effective_dates():
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-05-30",
        json={
            "amount": 1.0,
            "base": "EUR",
            "date": "2026-05-29",
            "rates": {"USD": 1.1644, "GBP": 0.86723},
        },
        status=200,
    )
    result = fetch_rates("2026-05-30", base="EUR", symbols=["USD", "GBP"], sleep=_no_sleep)
    assert result.requested_date == "2026-05-30"
    assert result.effective_date == "2026-05-29"


@responses.activate
def test_missing_currency_is_absent_without_error():
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-06-01",
        json={"amount": 1.0, "base": "EUR", "date": "2026-06-01", "rates": {"USD": 1.1646}},
        status=200,
    )
    result = fetch_rates("2026-06-01", base="EUR", symbols=["USD", "MAD"], sleep=_no_sleep)
    assert "MAD" not in result.rates
    assert result.rates == {"USD": 1.1646}


@responses.activate
def test_429_then_200_retries_once_and_waits_once():
    responses.add(responses.GET, f"{FAKE_BASE_URL}/2026-06-01", status=429)
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-06-01",
        json={"amount": 1.0, "base": "EUR", "date": "2026-06-01", "rates": {"USD": 1.1646}},
        status=200,
    )
    waits: list[float] = []
    result = fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=waits.append)
    assert result.rates == {"USD": 1.1646}
    assert len(responses.calls) == 2
    assert len(waits) == 1


@responses.activate
def test_persistent_500_raises_transient_error_after_four_attempts():
    for _ in range(4):
        responses.add(responses.GET, f"{FAKE_BASE_URL}/2026-06-01", status=500)
    with pytest.raises(FxTransientError):
        fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert len(responses.calls) == 4


@responses.activate
def test_520_with_html_body_raises_transient_error_without_json_parsing():
    for _ in range(4):
        responses.add(
            responses.GET,
            f"{FAKE_BASE_URL}/2026-06-01",
            body="<html><head><title>522</title></head><body>error code: 522</body></html>",
            status=520,
            content_type="text/html",
        )
    with pytest.raises(FxTransientError):
        fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=_no_sleep)


@responses.activate
def test_read_timeout_is_retried():
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-06-01",
        body=requests.exceptions.ReadTimeout("read timed out"),
    )
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-06-01",
        json={"amount": 1.0, "base": "EUR", "date": "2026-06-01", "rates": {"USD": 1.1646}},
        status=200,
    )
    result = fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert result.rates == {"USD": 1.1646}
    assert len(responses.calls) == 2


@responses.activate
def test_connection_error_is_retried():
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-06-01",
        body=requests.exceptions.ConnectionError("connection refused"),
    )
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-06-01",
        json={"amount": 1.0, "base": "EUR", "date": "2026-06-01", "rates": {"USD": 1.1646}},
        status=200,
    )
    result = fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert result.rates == {"USD": 1.1646}
    assert len(responses.calls) == 2


@responses.activate
def test_404_is_not_retried():
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2030-01-01",
        json={"message": "not found"},
        status=404,
    )
    with pytest.raises(FxPermanentError):
        fetch_rates("2030-01-01", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert len(responses.calls) == 1


@responses.activate
def test_422_is_not_retried():
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-13-45",
        json={"message": "invalid date"},
        status=422,
    )
    with pytest.raises(FxPermanentError):
        fetch_rates("2026-13-45", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert len(responses.calls) == 1


@responses.activate
def test_403_is_not_retried():
    responses.add(responses.GET, f"{FAKE_BASE_URL}/2026-06-01", status=403)
    with pytest.raises(FxPermanentError):
        fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert len(responses.calls) == 1


def test_timeouts_are_5_and_10_seconds_and_injected_into_the_http_call():
    captured_kwargs: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"amount": 1.0, "base": "EUR", "date": "2026-06-01", "rates": {"USD": 1.1646}}

    class _FakeSession:
        def get(self, url, params=None, timeout=None):
            captured_kwargs["timeout"] = timeout
            return _FakeResponse()

    result = fetch_rates(
        "2026-06-01",
        base="EUR",
        symbols=["USD"],
        session=_FakeSession(),
        sleep=_no_sleep,
    )
    assert captured_kwargs["timeout"] == (5.0, 10.0)
    assert result.rates == {"USD": 1.1646}


def test_jitter_stays_within_25_percent_bounds_and_is_not_constant():
    rng = random_module.Random(0)
    delays = [_jittered_delay(1.0, rng.random) for _ in range(60)]
    assert all(0.75 <= delay <= 1.25 for delay in delays)
    assert len(set(delays)) > 1


@responses.activate
def test_200_with_unparsable_json_body_is_retried_then_raises_transient_error():
    for _ in range(4):
        responses.add(
            responses.GET,
            f"{FAKE_BASE_URL}/2026-06-01",
            body="not json",
            status=200,
            content_type="text/plain",
        )
    with pytest.raises(FxTransientError):
        fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert len(responses.calls) == 4


@responses.activate
def test_200_with_missing_required_key_is_retried_then_raises_transient_error():
    for _ in range(4):
        responses.add(
            responses.GET,
            f"{FAKE_BASE_URL}/2026-06-01",
            json={"amount": 1.0, "base": "EUR", "date": "2026-06-01"},
            status=200,
        )
    with pytest.raises(FxTransientError):
        fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=_no_sleep)
    assert len(responses.calls) == 4


@responses.activate
def test_500_retry_delays_are_jittered_within_expected_bounds():
    for _ in range(4):
        responses.add(responses.GET, f"{FAKE_BASE_URL}/2026-06-01", status=500)
    waits: list[float] = []
    with pytest.raises(FxTransientError):
        fetch_rates("2026-06-01", base="EUR", symbols=["USD"], sleep=waits.append)
    assert len(waits) == 3
    assert 0.75 <= waits[0] <= 1.25
    assert 1.5 <= waits[1] <= 2.5
    assert 3.0 <= waits[2] <= 5.0
    assert waits != [1.0, 2.0, 4.0]


@responses.activate
def test_request_url_contains_date_base_and_symbols():
    responses.add(
        responses.GET,
        f"{FAKE_BASE_URL}/2026-06-01",
        json={"amount": 1.0, "base": "EUR", "date": "2026-06-01", "rates": {"USD": 1.1646}},
        status=200,
    )
    fetch_rates("2026-06-01", base="EUR", symbols=["USD", "GBP"], sleep=_no_sleep)
    sent_url = responses.calls[0].request.url
    parsed = urlparse(sent_url)
    assert parsed.path.endswith("/2026-06-01")
    query = parse_qs(parsed.query)
    assert query["base"] == ["EUR"]
    assert query["symbols"] == ["USD,GBP"]
