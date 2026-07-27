"""Derive fx_status, unavailable_reason, and carry-forward flags for a rate lookup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

CARRY_FORWARD_MAX_DAYS = 7

STATUS_OK = "ok"
STATUS_CARRIED_FORWARD = "carried_forward"
STATUS_UNAVAILABLE = "unavailable"

CURRENCY_NOT_PUBLISHED = "currency_not_published"
RATE_TOO_OLD = "rate_too_old"
NO_DATA_FOR_DATE = "no_data_for_date"
FETCH_FAILED = "fetch_failed"

_NON_FINAL_UNAVAILABLE_REASONS = frozenset({FETCH_FAILED})


@dataclass(frozen=True)
class FxStatusResult:
    fx_status: str
    is_carried_forward: bool
    effective_rate_date: date | None
    rate: float | None
    unavailable_reason: str | None


def classify(
    requested_date: date,
    effective_date: date,
    rate: float | None,
) -> FxStatusResult:
    if rate is None:
        return FxStatusResult(
            fx_status=STATUS_UNAVAILABLE,
            is_carried_forward=False,
            effective_rate_date=None,
            rate=None,
            unavailable_reason=CURRENCY_NOT_PUBLISHED,
        )

    age_days = (requested_date - effective_date).days

    if age_days < 0:
        # an effective date after the requested date should never happen; treated as an
        # unexplained fetch problem rather than a real "too old" rate, so it gets retried
        return FxStatusResult(
            fx_status=STATUS_UNAVAILABLE,
            is_carried_forward=False,
            effective_rate_date=effective_date,
            rate=None,
            unavailable_reason=FETCH_FAILED,
        )

    if age_days == 0:
        return FxStatusResult(
            fx_status=STATUS_OK,
            is_carried_forward=False,
            effective_rate_date=effective_date,
            rate=rate,
            unavailable_reason=None,
        )

    if age_days <= CARRY_FORWARD_MAX_DAYS:
        return FxStatusResult(
            fx_status=STATUS_CARRIED_FORWARD,
            is_carried_forward=True,
            effective_rate_date=effective_date,
            rate=rate,
            unavailable_reason=None,
        )

    return FxStatusResult(
        fx_status=STATUS_UNAVAILABLE,
        is_carried_forward=False,
        effective_rate_date=effective_date,
        rate=None,
        unavailable_reason=RATE_TOO_OLD,
    )


def permanent_error_result() -> FxStatusResult:
    return FxStatusResult(
        fx_status=STATUS_UNAVAILABLE,
        is_carried_forward=False,
        effective_rate_date=None,
        rate=None,
        unavailable_reason=NO_DATA_FOR_DATE,
    )


def transient_error_result() -> FxStatusResult:
    return FxStatusResult(
        fx_status=STATUS_UNAVAILABLE,
        is_carried_forward=False,
        effective_rate_date=None,
        rate=None,
        unavailable_reason=FETCH_FAILED,
    )


def is_final(unavailable_reason: str | None) -> bool:
    return unavailable_reason not in _NON_FINAL_UNAVAILABLE_REASONS
