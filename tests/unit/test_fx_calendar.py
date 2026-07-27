from __future__ import annotations

from datetime import date, timedelta

from payments.fx.calendar import (
    CARRY_FORWARD_MAX_DAYS,
    CURRENCY_NOT_PUBLISHED,
    FETCH_FAILED,
    NO_DATA_FOR_DATE,
    RATE_TOO_OLD,
    STATUS_CARRIED_FORWARD,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    classify,
    is_final,
    permanent_error_result,
    transient_error_result,
)


def test_same_date_is_ok():
    requested = date(2026, 6, 1)
    result = classify(requested, requested, 1.1646)
    assert result.fx_status == STATUS_OK
    assert result.is_carried_forward is False
    assert result.effective_rate_date == requested
    assert result.rate == 1.1646
    assert result.unavailable_reason is None


def test_boundary_at_carry_forward_max_days_is_still_carried_forward():
    requested = date(2026, 6, 8)
    effective = requested - timedelta(days=CARRY_FORWARD_MAX_DAYS)
    result = classify(requested, effective, 1.2345)
    assert result.fx_status == STATUS_CARRIED_FORWARD
    assert result.is_carried_forward is True
    assert result.effective_rate_date == effective
    assert result.rate == 1.2345
    assert result.unavailable_reason is None


def test_one_day_past_carry_forward_max_days_is_unavailable_with_rate_too_old():
    requested = date(2026, 6, 8)
    effective = requested - timedelta(days=CARRY_FORWARD_MAX_DAYS + 1)
    result = classify(requested, effective, 1.2345)
    assert result.fx_status == STATUS_UNAVAILABLE
    assert result.is_carried_forward is False
    assert result.effective_rate_date == effective
    assert result.rate is None
    assert result.unavailable_reason == RATE_TOO_OLD


def test_missing_currency_is_unavailable_with_currency_not_published():
    requested = date(2026, 6, 1)
    result = classify(requested, requested, None)
    assert result.fx_status == STATUS_UNAVAILABLE
    assert result.is_carried_forward is False
    assert result.effective_rate_date is None
    assert result.rate is None
    assert result.unavailable_reason == CURRENCY_NOT_PUBLISHED


def test_effective_date_after_requested_date_is_unavailable_with_fetch_failed():
    requested = date(2026, 6, 1)
    effective = date(2026, 6, 2)
    result = classify(requested, effective, 1.1646)
    assert result.fx_status == STATUS_UNAVAILABLE
    assert result.is_carried_forward is False
    assert result.rate is None
    assert result.unavailable_reason == FETCH_FAILED


def test_permanent_error_result_is_unavailable_with_no_data_for_date():
    result = permanent_error_result()
    assert result.fx_status == STATUS_UNAVAILABLE
    assert result.rate is None
    assert result.unavailable_reason == NO_DATA_FOR_DATE


def test_transient_error_result_is_unavailable_with_fetch_failed():
    result = transient_error_result()
    assert result.fx_status == STATUS_UNAVAILABLE
    assert result.rate is None
    assert result.unavailable_reason == FETCH_FAILED


def test_only_fetch_failed_is_not_final():
    assert is_final(None) is True
    assert is_final(CURRENCY_NOT_PUBLISHED) is True
    assert is_final(RATE_TOO_OLD) is True
    assert is_final(NO_DATA_FOR_DATE) is True
    assert is_final(FETCH_FAILED) is False


def test_only_three_status_values_are_ever_produced():
    requested = date(2026, 6, 8)
    cases = [
        classify(requested, requested, 1.0),
        classify(requested, requested - timedelta(days=3), 1.0),
        classify(requested, requested - timedelta(days=CARRY_FORWARD_MAX_DAYS), 1.0),
        classify(requested, requested - timedelta(days=CARRY_FORWARD_MAX_DAYS + 1), 1.0),
        classify(requested, requested, None),
    ]
    statuses = {case.fx_status for case in cases}
    assert statuses == {STATUS_OK, STATUS_CARRIED_FORWARD, STATUS_UNAVAILABLE}
