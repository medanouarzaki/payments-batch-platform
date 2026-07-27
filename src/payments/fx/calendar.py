"""Derive fx_status and carry-forward flags from requested vs effective dates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

CARRY_FORWARD_MAX_DAYS = 7

STATUS_OK = "ok"
STATUS_CARRIED_FORWARD = "carried_forward"
STATUS_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class FxStatusResult:
    fx_status: str
    is_carried_forward: bool
    effective_rate_date: date | None
    rate: float | None


def classify(
    requested_date: date,
    effective_date: date | None,
    rate: float | None,
) -> FxStatusResult:
    if rate is None or effective_date is None:
        return FxStatusResult(
            fx_status=STATUS_UNAVAILABLE,
            is_carried_forward=False,
            effective_rate_date=None,
            rate=None,
        )

    age_days = (requested_date - effective_date).days

    if age_days == 0:
        return FxStatusResult(
            fx_status=STATUS_OK,
            is_carried_forward=False,
            effective_rate_date=effective_date,
            rate=rate,
        )

    if 0 < age_days <= CARRY_FORWARD_MAX_DAYS:
        return FxStatusResult(
            fx_status=STATUS_CARRIED_FORWARD,
            is_carried_forward=True,
            effective_rate_date=effective_date,
            rate=rate,
        )

    return FxStatusResult(
        fx_status=STATUS_UNAVAILABLE,
        is_carried_forward=False,
        effective_rate_date=effective_date,
        rate=None,
    )
