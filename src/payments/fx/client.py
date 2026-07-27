"""HTTP client for the Frankfurter exchange rate API."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import requests

from payments.config import get_settings

CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
JITTER_FRACTION = 0.25


class FxClientError(Exception):
    """Base class for exchange rate client errors."""


class FxTransientError(FxClientError):
    """Retryable failure: 429, any 5xx, a connection failure, or a timeout."""


class FxPermanentError(FxClientError):
    """Non-retryable failure: 404, 422, or any other 4xx."""


@dataclass(frozen=True)
class ExchangeRates:
    requested_date: str
    effective_date: str
    base_currency: str
    rates: dict[str, float]


def _jittered_delay(base_seconds: float, random_func: Callable[[], float]) -> float:
    jitter = 1.0 + JITTER_FRACTION * (2.0 * random_func() - 1.0)
    return base_seconds * jitter


def _retry_or_raise(
    attempt: int,
    sleep: Callable[[float], None],
    random_func: Callable[[], float],
    message: str,
    cause: BaseException | None = None,
) -> int:
    if attempt >= MAX_ATTEMPTS:
        raise FxTransientError(message) from cause
    sleep(_jittered_delay(RETRY_BACKOFF_SECONDS[attempt - 1], random_func))
    return attempt + 1


def fetch_rates(
    date: str,
    *,
    base: str,
    symbols: Sequence[str],
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    random_func: Callable[[], float] = random.random,
) -> ExchangeRates:
    settings = get_settings()
    http = session if session is not None else requests.Session()
    url = f"{settings.fx_api_base_url}/{date}"
    params = {"base": base, "symbols": ",".join(symbols)}

    attempt = 1
    while True:
        try:
            response = http.get(
                url, params=params, timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            attempt = _retry_or_raise(
                attempt,
                sleep,
                random_func,
                f"exchange rate API request failed after {attempt} attempts",
                cause=exc,
            )
            continue

        status = response.status_code
        if status == 200:
            try:
                body = response.json()
                effective_date = body["date"]
                base_currency = body["base"]
                rates = dict(body["rates"])
            except (ValueError, KeyError) as exc:
                # transient: a bad page clears on retry, a schema change surfaces after 4 tries
                attempt = _retry_or_raise(
                    attempt,
                    sleep,
                    random_func,
                    f"exchange rate API returned an unreadable 200 body after {attempt} attempts",
                    cause=exc,
                )
                continue
            return ExchangeRates(
                requested_date=date,
                effective_date=effective_date,
                base_currency=base_currency,
                rates=rates,
            )

        if status == 429 or status >= 500:
            attempt = _retry_or_raise(
                attempt,
                sleep,
                random_func,
                f"exchange rate API returned {status} after {attempt} attempts",
            )
            continue

        raise FxPermanentError(f"exchange rate API returned {status}: {response.text}")
