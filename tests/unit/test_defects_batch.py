"""Batch-level properties of apply_defects/build_daily_batch on a full daily batch."""

import math
import re
from collections import defaultdict
from dataclasses import replace
from datetime import date

import pytest

from payments.config import load_defect_rates
from payments.generator.defects import _parse_event_timestamp, apply_defects
from payments.generator.generate import batch_fingerprint, build_daily_batch, generate_batch
from payments.generator.schema import COUNTRIES, validate_row

N_ROWS = 50000
RUN_DATE = date(2026, 7, 21)
SEED = 4242

# Pinned to the rates committed in config/defects.yml. The tolerance test compares
# observed behavior against this fixed baseline rather than against whatever the
# live config file currently says, so an uncommitted edit to the rates is caught
# as a regression instead of silently redefining what "correct" means.
_PINNED_RATES = {
    "duplicate_exact": 0.005,
    "near_duplicate": 0.003,
    "late_event": 0.02,
    "missing_currency": 0.004,
    "unknown_currency": 0.002,
    "lowercase_currency": 0.01,
    "non_positive_amount": 0.003,
    "amount_formatting": 0.01,
    "malformed_country": 0.015,
    "naive_timestamp": 0.08,
    "offset_timestamp": 0.10,
    "missing_transaction_id": 0.0005,
}

_NAIVE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
_OFFSET_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")


def _currency_touched(value) -> bool:
    if value in (None, ""):
        return True
    if value in ("XXX", "ZZZ"):
        return True
    return isinstance(value, str) and value == value.lower() and value != value.upper()


def _amount_touched(value: str) -> bool:
    if "," in value:
        return True
    return float(value) <= 0


def _timestamp_touched(value: str) -> bool:
    return bool(_NAIVE_PATTERN.match(value)) or bool(_OFFSET_PATTERN.match(value))


@pytest.fixture(scope="module")
def rates():
    return load_defect_rates()


@pytest.fixture(scope="module")
def batch(rates):
    raw_rows = generate_batch(RUN_DATE, n_rows=N_ROWS, seed=SEED)
    final_rows, report = apply_defects(raw_rows, rates, SEED, RUN_DATE)
    return raw_rows, final_rows, report


def test_defect_counts_within_tolerance(batch):
    _, _, report = batch
    n = report.rows_in
    header = f"{'defect':<24}{'rate':>8}{'expected':>12}{'observed':>10}{'band':>10}{'z':>8}"
    lines = [header]
    failures = []
    for name, observed in report.counts.items():
        p = _PINNED_RATES[name]
        expected = n * p
        std = math.sqrt(n * p * (1 - p)) if 0 < p < 1 else 0.0
        band = max(5.0, 4 * std)
        z = (observed - expected) / std if std > 0 else 0.0
        lines.append(f"{name:<24}{p:>8.4f}{expected:>12.2f}{observed:>10d}{band:>10.2f}{z:>8.2f}")
        if not (expected - band <= observed <= expected + band):
            failures.append(name)
    print("\n".join(lines))
    assert not failures, f"defects out of tolerance: {failures}"


def test_all_defects_are_present(batch):
    _, _, report = batch
    for name, observed in report.counts.items():
        assert observed > 0, f"{name} count is zero"


def test_all_rows_pass_contract(batch):
    _, final_rows, _ = batch
    for row in final_rows:
        validate_row(row)


def test_family_exclusivity(batch):
    raw_rows, _, report = batch
    currency_touched = sum(1 for row in raw_rows if _currency_touched(row["currency"]))
    amount_touched = sum(1 for row in raw_rows if _amount_touched(row["amount"]))
    timestamp_touched = sum(1 for row in raw_rows if _timestamp_touched(row["event_timestamp"]))

    assert currency_touched == (
        report.counts["missing_currency"]
        + report.counts["unknown_currency"]
        + report.counts["lowercase_currency"]
    )
    assert amount_touched == (
        report.counts["non_positive_amount"] + report.counts["amount_formatting"]
    )
    assert timestamp_touched == (
        report.counts["naive_timestamp"] + report.counts["offset_timestamp"]
    )


def test_row_count_accounting(batch):
    _, _, report = batch
    assert report.rows_out - report.rows_in == (
        report.counts["duplicate_exact"] + report.counts["near_duplicate"]
    )


def test_near_and_exact_duplicates_match_expected_counts(batch):
    raw_rows, final_rows, report = batch
    original_ids = {id(row) for row in raw_rows}
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in final_rows:
        if row["transaction_id"] is not None:
            groups[row["transaction_id"]].append(row)

    near_duplicate_count = 0
    exact_duplicate_count = 0
    for rows_with_id in groups.values():
        if len(rows_with_id) < 2:
            continue
        originals = [row for row in rows_with_id if id(row) in original_ids]
        assert len(originals) == 1
        base = originals[0]
        for row in rows_with_id:
            if row is base:
                continue
            if row["status"] == base["status"] and row["amount"] == base["amount"]:
                exact_duplicate_count += 1
            else:
                near_duplicate_count += 1

    assert near_duplicate_count == report.counts["near_duplicate"]
    assert exact_duplicate_count == report.counts["duplicate_exact"]


def test_late_events_precede_ingestion_date(batch, rates):
    raw_rows, _, report = batch
    late_count = 0
    for row in raw_rows:
        moment = _parse_event_timestamp(row["event_timestamp"])
        event_date = moment.date()
        assert row["ingestion_date"] == RUN_DATE
        if event_date < RUN_DATE:
            late_count += 1
            delay_days = (RUN_DATE - event_date).days
            assert 1 <= delay_days <= rates.late_event_max_days
    assert late_count == report.counts["late_event"]


def test_build_daily_batch_is_deterministic():
    rows1, report1 = build_daily_batch(RUN_DATE, n_rows=5000, seed=99)
    rows2, report2 = build_daily_batch(RUN_DATE, n_rows=5000, seed=99)
    assert batch_fingerprint(rows1) == batch_fingerprint(rows2)
    assert report1 == report2


def _malformed_country_ids(original_ids, raw_rows):
    result = set()
    for original_id, row in zip(original_ids, raw_rows, strict=True):
        if row["debtor_country"] not in COUNTRIES or row["creditor_country"] not in COUNTRIES:
            result.add(original_id)
    return result


def _missing_transaction_id_ids(original_ids, raw_rows):
    result = {
        original_id
        for original_id, row in zip(original_ids, raw_rows, strict=True)
        if row["transaction_id"] is None
    }
    return result


def _lowercase_currency_ids(original_ids, pristine_rows, mutated_rows):
    result = set()
    for original_id, pristine, mutated in zip(
        original_ids, pristine_rows, mutated_rows, strict=True
    ):
        original_currency = pristine["currency"]
        value = mutated["currency"]
        if (
            isinstance(value, str)
            and value == original_currency.lower()
            and value != original_currency
        ):
            result.add(original_id)
    return result


@pytest.mark.parametrize(
    "currency_rate_name", ["missing_currency", "unknown_currency", "lowercase_currency"]
)
def test_currency_family_rate_does_not_shift_later_independent_defects(rates, currency_rate_name):
    # Doubling any one currency-family rate must not shift malformed_country or
    # missing_transaction_id, which sit later in the orchestration order and must
    # draw from their own dedicated generators. All three family members are
    # exercised (not just lowercase_currency) because a member whose mutator
    # itself never consumes extra randomness (lowercase_currency's does not: it
    # only lowercases a string) would not perturb a generator shared downstream,
    # silently hiding exactly the bug this test exists to catch.
    base_raw = generate_batch(RUN_DATE, n_rows=5000, seed=SEED)
    original_ids = [row["transaction_id"] for row in base_raw]
    raw_a = [row.copy() for row in base_raw]
    raw_b = [row.copy() for row in base_raw]

    rates_a = rates
    current_rate = getattr(rates, currency_rate_name)
    rates_b = replace(rates, **{currency_rate_name: min(current_rate * 2, 0.9)})

    apply_defects(raw_a, rates_a, SEED, RUN_DATE)
    apply_defects(raw_b, rates_b, SEED, RUN_DATE)

    assert _malformed_country_ids(original_ids, raw_a) == _malformed_country_ids(
        original_ids, raw_b
    )
    assert _missing_transaction_id_ids(original_ids, raw_a) == _missing_transaction_id_ids(
        original_ids, raw_b
    )


def test_late_event_rate_does_not_shift_lowercase_currency(rates):
    base_raw = generate_batch(RUN_DATE, n_rows=5000, seed=SEED)
    original_ids = [row["transaction_id"] for row in base_raw]
    raw_a = [row.copy() for row in base_raw]
    raw_b = [row.copy() for row in base_raw]

    rates_a = rates
    rates_b = replace(rates, late_event=min(rates.late_event * 2, 1.0))

    apply_defects(raw_a, rates_a, SEED, RUN_DATE)
    apply_defects(raw_b, rates_b, SEED, RUN_DATE)

    assert _lowercase_currency_ids(original_ids, base_raw, raw_a) == _lowercase_currency_ids(
        original_ids, base_raw, raw_b
    )


def test_defect_counts_vary_across_seeds_forbidding_fixed_size_allocation(batch, rates):
    _, _, report_1 = batch
    reports = [report_1]
    for seed in (SEED + 1, SEED + 2):
        raw_rows = generate_batch(RUN_DATE, n_rows=N_ROWS, seed=seed)
        _, report = apply_defects(raw_rows, rates, seed, RUN_DATE)
        reports.append(report)

    differing = sum(
        1 for name in reports[0].counts if reports[0].counts[name] != reports[1].counts[name]
    )
    assert differing >= 8, (
        f"only {differing}/12 counts differ between two seeds: "
        f"{reports[0].counts} vs {reports[1].counts}"
    )

    # A count identical across three independent seeds is the signature of a
    # fixed-size allocation (round(rate * n) does not depend on the seed at
    # all), not of Bernoulli variance: even the rarest defect ties across two
    # draws only occasionally, and virtually never across three.
    tied_across_all_seeds = [
        name
        for name in reports[0].counts
        if reports[0].counts[name] == reports[1].counts[name] == reports[2].counts[name]
    ]
    assert not tied_across_all_seeds, (
        f"counts identical across three independent seeds, looks like a fixed-size "
        f"allocation rather than a Bernoulli draw: {tied_across_all_seeds}"
    )


def test_defect_counts_deviate_from_exact_rounded_expectation(batch, rates):
    _, _, report = batch
    n = report.rows_in
    deviating = [
        name
        for name, observed in report.counts.items()
        if observed != round(n * getattr(rates, name))
    ]
    assert len(deviating) >= 6, f"only {len(deviating)}/12 counts deviate: {deviating}"
