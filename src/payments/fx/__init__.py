"""Exchange rate HTTP client, cache, and cache-first orchestration."""

from payments.fx.cache import FxRateRow, create_schema, fetch_cached_rows, upsert_rows
from payments.fx.calendar import (
    CARRY_FORWARD_MAX_DAYS,
    CURRENCY_NOT_PUBLISHED,
    FETCH_FAILED,
    NO_DATA_FOR_DATE,
    RATE_TOO_OLD,
    STATUS_CARRIED_FORWARD,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    FxStatusResult,
    classify,
    is_final,
    permanent_error_result,
    transient_error_result,
)
from payments.fx.client import (
    ExchangeRates,
    FxClientError,
    FxPermanentError,
    FxTransientError,
    fetch_rates,
)
from payments.fx.service import fetch_fx_rates

__all__ = [
    "CARRY_FORWARD_MAX_DAYS",
    "CURRENCY_NOT_PUBLISHED",
    "FETCH_FAILED",
    "NO_DATA_FOR_DATE",
    "RATE_TOO_OLD",
    "STATUS_CARRIED_FORWARD",
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "ExchangeRates",
    "FxClientError",
    "FxPermanentError",
    "FxRateRow",
    "FxStatusResult",
    "FxTransientError",
    "classify",
    "create_schema",
    "fetch_cached_rows",
    "fetch_fx_rates",
    "fetch_rates",
    "is_final",
    "permanent_error_result",
    "transient_error_result",
    "upsert_rows",
]
