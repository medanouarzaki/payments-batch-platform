from __future__ import annotations

from datetime import date, timedelta

from payments.fx.calendar import (
    CARRY_FORWARD_MAX_DAYS,
    STATUS_CARRIED_FORWARD,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    classify,
)


def test_same_date_is_ok():
    requested = date(2026, 6, 1)
    result = classify(requested, requested, 1.1646)
    assert result.fx_status == STATUS_OK
    assert result.is_carried_forward is False
    assert result.effective_rate_date == requested
    assert result.rate == 1.1646


def test_boundary_at_carry_forward_max_days_is_still_carried_forward():
    requested = date(2026, 6, 8)
    effective = requested - timedelta(days=CARRY_FORWARD_MAX_DAYS)
    result = classify(requested, effective, 1.2345)
    assert result.fx_status == STATUS_CARRIED_FORWARD
    assert result.is_carried_forward is True
    assert result.effective_rate_date == effective
    assert result.rate == 1.2345


def test_one_day_past_carry_forward_max_days_is_unavailable():
    requested = date(2026, 6, 8)
    effective = requested - timedelta(days=CARRY_FORWARD_MAX_DAYS + 1)
    result = classify(requested, effective, 1.2345)
    assert result.fx_status == STATUS_UNAVAILABLE
    assert result.is_carried_forward is False
    assert result.effective_rate_date == effective
    assert result.rate is None


def test_missing_currency_is_unavailable_with_null_effective_date_and_rate():
    requested = date(2026, 6, 1)
    result = classify(requested, None, None)
    assert result.fx_status == STATUS_UNAVAILABLE
    assert result.is_carried_forward is False
    assert result.effective_rate_date is None
    assert result.rate is None


def test_only_three_status_values_are_ever_produced():
    requested = date(2026, 6, 8)
    cases = [
        classify(requested, requested, 1.0),
        classify(requested, requested - timedelta(days=3), 1.0),
        classify(requested, requested - timedelta(days=CARRY_FORWARD_MAX_DAYS), 1.0),
        classify(requested, requested - timedelta(days=CARRY_FORWARD_MAX_DAYS + 1), 1.0),
        classify(requested, None, None),
    ]
    statuses = {case.fx_status for case in cases}
    assert statuses == {STATUS_OK, STATUS_CARRIED_FORWARD, STATUS_UNAVAILABLE}
