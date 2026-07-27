"""Isolated behavior of each defect-catalog function, in isolation from apply_defects."""

import random
import re
from datetime import UTC, date, datetime

import pytest

from payments.generator.defects import (
    inject_amount_formatting,
    inject_duplicate_exact,
    inject_late_event,
    inject_lowercase_currency,
    inject_malformed_country,
    inject_missing_currency,
    inject_missing_transaction_id,
    inject_naive_timestamp,
    inject_near_duplicate,
    inject_non_positive_amount,
    inject_offset_timestamp,
    inject_unknown_currency,
)
from payments.generator.generate import batch_fingerprint, generate_batch
from payments.generator.schema import STATUSES

_ALPHA3_CODES = {"FRA", "DEU", "ESP", "ITA", "NLD", "BEL", "GBR", "CHE", "SWE", "POL", "MAR"}


@pytest.fixture(scope="module")
def clean_rows():
    return generate_batch(date(2026, 7, 21), n_rows=2000, seed=1)


def _copy(rows):
    return [row.copy() for row in rows]


def test_inject_late_event(clean_rows):
    rows = _copy(clean_rows)
    rng = random.Random(42)
    count = inject_late_event(rows, 1.0, rng, min_days=1, max_days=5)
    assert count == len(rows)
    for original, row in zip(clean_rows, rows, strict=True):
        raw = row["event_timestamp"]
        assert raw.endswith("Z")
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
        original_parsed = datetime.strptime(original["event_timestamp"], "%Y-%m-%dT%H:%M:%SZ")
        delta_days = (original_parsed.date() - parsed.date()).days
        assert 1 <= delta_days <= 5

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_late_event(rows_zero, 0.0, random.Random(42))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_naive_timestamp(clean_rows):
    rows = _copy(clean_rows)
    count = inject_naive_timestamp(rows, 1.0, random.Random(1))
    assert count == len(rows)
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
    for row in rows:
        assert pattern.match(row["event_timestamp"])

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_naive_timestamp(rows_zero, 0.0, random.Random(1))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_offset_timestamp(clean_rows):
    rows = _copy(clean_rows)
    count = inject_offset_timestamp(rows, 1.0, random.Random(2))
    assert count == len(rows)
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\+|-)\d{2}:\d{2}$")
    for original, row in zip(clean_rows, rows, strict=True):
        raw = row["event_timestamp"]
        assert pattern.match(raw)
        converted = datetime.fromisoformat(raw).astimezone(UTC)
        original_parsed = datetime.strptime(
            original["event_timestamp"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        assert converted == original_parsed

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_offset_timestamp(rows_zero, 0.0, random.Random(2))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_missing_currency(clean_rows):
    rows = _copy(clean_rows)
    count = inject_missing_currency(rows, 1.0, random.Random(3))
    assert count == len(rows)
    for row in rows:
        assert row["currency"] in (None, "")

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_missing_currency(rows_zero, 0.0, random.Random(3))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_unknown_currency(clean_rows):
    rows = _copy(clean_rows)
    count = inject_unknown_currency(rows, 1.0, random.Random(4))
    assert count == len(rows)
    for row in rows:
        assert row["currency"] in ("XXX", "ZZZ")

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_unknown_currency(rows_zero, 0.0, random.Random(4))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_lowercase_currency(clean_rows):
    rows = _copy(clean_rows)
    count = inject_lowercase_currency(rows, 1.0, random.Random(5))
    assert count == len(rows)
    for original, row in zip(clean_rows, rows, strict=True):
        assert row["currency"] == original["currency"].lower()
        assert row["currency"] == row["currency"].lower()
        assert row["currency"] != row["currency"].upper()

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_lowercase_currency(rows_zero, 0.0, random.Random(5))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_non_positive_amount(clean_rows):
    rows = _copy(clean_rows)
    count = inject_non_positive_amount(rows, 1.0, random.Random(6))
    assert count == len(rows)
    for row in rows:
        assert float(row["amount"]) <= 0
        integer_and_decimal = row["amount"].lstrip("-").split(".")
        assert len(integer_and_decimal) == 2
        assert len(integer_and_decimal[1]) == 2

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_non_positive_amount(rows_zero, 0.0, random.Random(6))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_amount_formatting(clean_rows):
    rows = _copy(clean_rows)
    count = inject_amount_formatting(rows, 1.0, random.Random(7))
    assert count == len(rows)
    pattern = re.compile(r"^-?\d{1,3}( \d{3})*,\d{2}$")
    for original, row in zip(clean_rows, rows, strict=True):
        assert pattern.match(row["amount"])
        reparsed = row["amount"].replace(" ", "").replace(",", ".")
        assert float(reparsed) == pytest.approx(float(original["amount"]))

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_amount_formatting(rows_zero, 0.0, random.Random(7))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def _is_malformed_country_form(original_value: str, value) -> bool:
    if value is None:
        return True
    if value == "ZZ":
        return True
    if value in _ALPHA3_CODES:
        return True
    if value == original_value.lower():
        return True
    if len(value) == 3 and value[1] == " ":
        return True
    return False


def test_inject_malformed_country(clean_rows):
    rows = _copy(clean_rows)
    count = inject_malformed_country(rows, 1.0, random.Random(8))
    assert count == len(rows)
    for original, row in zip(clean_rows, rows, strict=True):
        changed_debtor = row["debtor_country"] != original["debtor_country"]
        changed_creditor = row["creditor_country"] != original["creditor_country"]
        assert changed_debtor != changed_creditor
        if changed_debtor:
            assert _is_malformed_country_form(original["debtor_country"], row["debtor_country"])
        else:
            assert _is_malformed_country_form(original["creditor_country"], row["creditor_country"])

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_malformed_country(rows_zero, 0.0, random.Random(8))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_missing_transaction_id(clean_rows):
    rows = _copy(clean_rows)
    count = inject_missing_transaction_id(rows, 1.0, random.Random(9))
    assert count == len(rows)
    for row in rows:
        assert row["transaction_id"] is None

    rows_zero = _copy(clean_rows)
    fingerprint_before = batch_fingerprint(rows_zero)
    count_zero = inject_missing_transaction_id(rows_zero, 0.0, random.Random(9))
    assert count_zero == 0
    assert batch_fingerprint(rows_zero) == fingerprint_before


def test_inject_duplicate_exact(clean_rows):
    rows = _copy(clean_rows)
    added = inject_duplicate_exact(rows, 1.0, random.Random(10))
    assert len(added) == len(rows)
    original_ids = {id(row) for row in rows}
    by_transaction_id = {row["transaction_id"]: row for row in rows}
    for new_row in added:
        assert id(new_row) not in original_ids
        assert new_row == by_transaction_id[new_row["transaction_id"]]

    rows_zero = _copy(clean_rows)
    added_zero = inject_duplicate_exact(rows_zero, 0.0, random.Random(10))
    assert added_zero == []


def test_inject_near_duplicate(clean_rows):
    rows = _copy(clean_rows)
    added = inject_near_duplicate(rows, 1.0, random.Random(11))
    assert len(added) == len(rows)
    by_transaction_id = {row["transaction_id"]: row for row in rows}
    for new_row in added:
        original = by_transaction_id[new_row["transaction_id"]]
        assert new_row["status"] != original["status"] or new_row["amount"] != original["amount"]
        assert new_row["status"] in STATUSES
        new_moment = datetime.strptime(new_row["event_timestamp"], "%Y-%m-%dT%H:%M:%SZ")
        original_moment = datetime.strptime(original["event_timestamp"], "%Y-%m-%dT%H:%M:%SZ")
        assert new_moment > original_moment

    rows_zero = _copy(clean_rows)
    added_zero = inject_near_duplicate(rows_zero, 0.0, random.Random(11))
    assert added_zero == []
