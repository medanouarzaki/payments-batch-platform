"""Controlled defect injection over an otherwise clean transaction batch.

Selection is a per-row Bernoulli trial (`rng.random() < rate`), not a fixed-size
draw: the number of affected rows is binomially distributed around its
expectation, never pinned to a precomputed target count.

Mutually exclusive families (currency, amount, timestamp) resolve with a single
`rng.random()` draw per row, compared against the members' cumulative
thresholds in catalog order. This guarantees each member keeps its exact
marginal probability and that two members of the same family never touch the
same row. The unavoidable consequence: within a family, changing one member's
rate shifts where the threshold boundaries fall for every other member of that
same family, so their attribution shifts too, even though their probabilities
stay individually correct. Across families, and for defects outside any
family, streams stay fully independent since each has its own dedicated
generator.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from payments.config import DefectRates
from payments.generator.schema import STATUSES

_OFFSETS: tuple[str, ...] = ("+01:00", "+02:00", "-05:00", "+05:30")

_ALPHA3: dict[str, str] = {
    "FR": "FRA",
    "DE": "DEU",
    "ES": "ESP",
    "IT": "ITA",
    "NL": "NLD",
    "BE": "BEL",
    "GB": "GBR",
    "CH": "CHE",
    "SE": "SWE",
    "PL": "POL",
    "MA": "MAR",
}

_MALFORMED_COUNTRY_VARIANTS: tuple[str, ...] = ("lower", "alpha3", "spaced", "zz", "none")

_CATALOG_ORDER: tuple[str, ...] = (
    "late_event",
    "naive_timestamp",
    "offset_timestamp",
    "missing_currency",
    "unknown_currency",
    "lowercase_currency",
    "non_positive_amount",
    "amount_formatting",
    "malformed_country",
    "missing_transaction_id",
    "duplicate_exact",
    "near_duplicate",
)


@dataclass(frozen=True)
class DefectReport:
    rows_in: int
    rows_out: int
    counts: dict[str, int]


def _defect_rng(seed: int, run_date: date, defect_name: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{run_date.isoformat()}:{defect_name}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _parse_amount(raw: str) -> float:
    return float(raw.replace(" ", "").replace(",", "."))


def _parse_event_timestamp(raw: str) -> datetime:
    if raw.endswith("Z"):
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    else:
        parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _mutate_late_event(row: dict, rng: random.Random, min_days: int, max_days: int) -> None:
    moment = _parse_event_timestamp(row["event_timestamp"])
    shifted = moment - timedelta(days=rng.randint(min_days, max_days))
    row["event_timestamp"] = shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mutate_naive_timestamp(row: dict, rng: random.Random) -> None:
    moment = _parse_event_timestamp(row["event_timestamp"])
    row["event_timestamp"] = moment.strftime("%Y-%m-%dT%H:%M:%S")


def _mutate_offset_timestamp(row: dict, rng: random.Random) -> None:
    moment = _parse_event_timestamp(row["event_timestamp"])
    offset_str = rng.choice(_OFFSETS)
    sign = 1 if offset_str[0] == "+" else -1
    hours, minutes = offset_str[1:].split(":")
    delta = sign * timedelta(hours=int(hours), minutes=int(minutes))
    local_moment = moment.astimezone(timezone(delta))
    row["event_timestamp"] = local_moment.strftime("%Y-%m-%d %H:%M:%S") + offset_str


def _mutate_missing_currency(row: dict, rng: random.Random) -> None:
    row["currency"] = rng.choice([None, ""])


def _mutate_unknown_currency(row: dict, rng: random.Random) -> None:
    row["currency"] = rng.choice(["XXX", "ZZZ"])


def _mutate_lowercase_currency(row: dict, rng: random.Random) -> None:
    row["currency"] = row["currency"].lower()


def _mutate_non_positive_amount(row: dict, rng: random.Random) -> None:
    if rng.random() < 0.5:
        row["amount"] = "0.00"
    else:
        magnitude = rng.uniform(1, 500)
        row["amount"] = f"-{magnitude:.2f}"


def _mutate_amount_formatting(row: dict, rng: random.Random) -> None:
    integer_part, _, decimal_part = row["amount"].partition(".")
    negative = integer_part.startswith("-")
    if negative:
        integer_part = integer_part[1:]
    groups = []
    while len(integer_part) > 3:
        groups.insert(0, integer_part[-3:])
        integer_part = integer_part[:-3]
    groups.insert(0, integer_part)
    formatted_integer = " ".join(groups)
    row["amount"] = f"{'-' if negative else ''}{formatted_integer},{decimal_part}"


def _mutate_malformed_country(row: dict, rng: random.Random) -> None:
    field = rng.choice(("debtor_country", "creditor_country"))
    original = row[field]
    variant = rng.choice(_MALFORMED_COUNTRY_VARIANTS)
    if variant == "lower":
        row[field] = original.lower()
    elif variant == "alpha3":
        row[field] = _ALPHA3.get(original, original.lower())
    elif variant == "spaced":
        row[field] = f"{original[0]} {original[1]}"
    elif variant == "zz":
        row[field] = "ZZ"
    else:
        row[field] = None


def _mutate_missing_transaction_id(row: dict, rng: random.Random) -> None:
    row["transaction_id"] = None


def inject_late_event(
    rows: list[dict],
    rate: float,
    rng: random.Random,
    min_days: int = 1,
    max_days: int = 5,
) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_late_event(row, rng, min_days, max_days)
            count += 1
    return count


def inject_naive_timestamp(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_naive_timestamp(row, rng)
            count += 1
    return count


def inject_offset_timestamp(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_offset_timestamp(row, rng)
            count += 1
    return count


def inject_missing_currency(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_missing_currency(row, rng)
            count += 1
    return count


def inject_unknown_currency(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_unknown_currency(row, rng)
            count += 1
    return count


def inject_lowercase_currency(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_lowercase_currency(row, rng)
            count += 1
    return count


def inject_non_positive_amount(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_non_positive_amount(row, rng)
            count += 1
    return count


def inject_amount_formatting(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_amount_formatting(row, rng)
            count += 1
    return count


def inject_malformed_country(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_malformed_country(row, rng)
            count += 1
    return count


def inject_missing_transaction_id(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = 0
    for row in rows:
        if rng.random() < rate:
            _mutate_missing_transaction_id(row, rng)
            count += 1
    return count


def inject_duplicate_exact(rows: list[dict], rate: float, rng: random.Random) -> list[dict]:
    new_rows = []
    for row in rows:
        if row["transaction_id"] is None:
            continue
        if rng.random() < rate:
            new_rows.append(row.copy())
    return new_rows


def inject_near_duplicate(rows: list[dict], rate: float, rng: random.Random) -> list[dict]:
    new_rows = []
    for row in rows:
        if row["transaction_id"] is None:
            continue
        if rng.random() < rate:
            new_row = row.copy()
            if rng.random() < 0.5:
                alternatives = [status for status in STATUSES if status != row["status"]]
                new_row["status"] = rng.choice(alternatives)
            else:
                new_row["amount"] = f"{_parse_amount(row['amount']) + rng.uniform(1, 50):.2f}"
            moment = _parse_event_timestamp(row["event_timestamp"])
            bumped = moment + timedelta(minutes=rng.randint(1, 15))
            new_row["event_timestamp"] = bumped.strftime("%Y-%m-%dT%H:%M:%SZ")
            new_rows.append(new_row)
    return new_rows


def apply_defects(
    rows: list[dict], rates: DefectRates, seed: int, run_date: date
) -> tuple[list[dict], DefectReport]:
    rows_in = len(rows)
    working = list(rows)
    counts: dict[str, int] = dict.fromkeys(_CATALOG_ORDER, 0)

    rng_late_event = _defect_rng(seed, run_date, "late_event")
    counts["late_event"] = inject_late_event(
        working,
        rates.late_event,
        rng_late_event,
        min_days=rates.late_event_min_days,
        max_days=rates.late_event_max_days,
    )

    rng_timestamp = _defect_rng(seed, run_date, "timestamp_family")
    for row in working:
        draw = rng_timestamp.random()
        if draw < rates.naive_timestamp:
            _mutate_naive_timestamp(row, rng_timestamp)
            counts["naive_timestamp"] += 1
        elif draw < rates.naive_timestamp + rates.offset_timestamp:
            _mutate_offset_timestamp(row, rng_timestamp)
            counts["offset_timestamp"] += 1

    rng_currency = _defect_rng(seed, run_date, "currency_family")
    for row in working:
        draw = rng_currency.random()
        if draw < rates.missing_currency:
            _mutate_missing_currency(row, rng_currency)
            counts["missing_currency"] += 1
        elif draw < rates.missing_currency + rates.unknown_currency:
            _mutate_unknown_currency(row, rng_currency)
            counts["unknown_currency"] += 1
        elif draw < rates.missing_currency + rates.unknown_currency + rates.lowercase_currency:
            _mutate_lowercase_currency(row, rng_currency)
            counts["lowercase_currency"] += 1

    rng_amount = _defect_rng(seed, run_date, "amount_family")
    for row in working:
        draw = rng_amount.random()
        if draw < rates.non_positive_amount:
            _mutate_non_positive_amount(row, rng_amount)
            counts["non_positive_amount"] += 1
        elif draw < rates.non_positive_amount + rates.amount_formatting:
            _mutate_amount_formatting(row, rng_amount)
            counts["amount_formatting"] += 1

    rng_malformed_country = _defect_rng(seed, run_date, "malformed_country")
    counts["malformed_country"] = inject_malformed_country(
        working, rates.malformed_country, rng_malformed_country
    )

    rng_missing_transaction_id = _defect_rng(seed, run_date, "missing_transaction_id")
    counts["missing_transaction_id"] = inject_missing_transaction_id(
        working, rates.missing_transaction_id, rng_missing_transaction_id
    )

    rng_near_duplicate = _defect_rng(seed, run_date, "near_duplicate")
    near_dup_rows = inject_near_duplicate(working, rates.near_duplicate, rng_near_duplicate)
    counts["near_duplicate"] = len(near_dup_rows)

    rng_duplicate_exact = _defect_rng(seed, run_date, "duplicate_exact")
    dup_rows = inject_duplicate_exact(working, rates.duplicate_exact, rng_duplicate_exact)
    counts["duplicate_exact"] = len(dup_rows)

    working = working + near_dup_rows + dup_rows

    rng_shuffle = _defect_rng(seed, run_date, "shuffle")
    rng_shuffle.shuffle(working)

    report = DefectReport(
        rows_in=rows_in,
        rows_out=len(working),
        counts={name: counts[name] for name in _CATALOG_ORDER},
    )
    return working, report
