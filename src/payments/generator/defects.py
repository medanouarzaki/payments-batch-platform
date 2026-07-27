"""Controlled defect injection over an otherwise clean transaction batch."""

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


def inject_late_event(
    rows: list[dict],
    rate: float,
    rng: random.Random,
    min_days: int = 1,
    max_days: int = 5,
) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        row = rows[i]
        moment = _parse_event_timestamp(row["event_timestamp"])
        shifted = moment - timedelta(days=rng.randint(min_days, max_days))
        row["event_timestamp"] = shifted.strftime("%Y-%m-%dT%H:%M:%SZ")
    return len(indices)


def inject_naive_timestamp(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        row = rows[i]
        moment = _parse_event_timestamp(row["event_timestamp"])
        row["event_timestamp"] = moment.strftime("%Y-%m-%dT%H:%M:%S")
    return len(indices)


def inject_offset_timestamp(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        row = rows[i]
        moment = _parse_event_timestamp(row["event_timestamp"])
        offset_str = rng.choice(_OFFSETS)
        sign = 1 if offset_str[0] == "+" else -1
        hours, minutes = offset_str[1:].split(":")
        delta = sign * timedelta(hours=int(hours), minutes=int(minutes))
        local_moment = moment.astimezone(timezone(delta))
        row["event_timestamp"] = local_moment.strftime("%Y-%m-%d %H:%M:%S") + offset_str
    return len(indices)


def inject_missing_currency(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        rows[i]["currency"] = rng.choice([None, ""])
    return len(indices)


def inject_unknown_currency(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        rows[i]["currency"] = rng.choice(["XXX", "ZZZ"])
    return len(indices)


def inject_lowercase_currency(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        rows[i]["currency"] = rows[i]["currency"].lower()
    return len(indices)


def inject_non_positive_amount(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        if rng.random() < 0.5:
            rows[i]["amount"] = "0.00"
        else:
            magnitude = rng.uniform(1, 500)
            rows[i]["amount"] = f"-{magnitude:.2f}"
    return len(indices)


def inject_amount_formatting(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        row = rows[i]
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
    return len(indices)


def inject_malformed_country(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        row = rows[i]
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
    return len(indices)


def inject_missing_transaction_id(rows: list[dict], rate: float, rng: random.Random) -> int:
    count = round(rate * len(rows))
    indices = rng.sample(range(len(rows)), count)
    for i in indices:
        rows[i]["transaction_id"] = None
    return len(indices)


def inject_duplicate_exact(rows: list[dict], rate: float, rng: random.Random) -> list[dict]:
    eligible = [row for row in rows if row["transaction_id"] is not None]
    count = min(round(rate * len(rows)), len(eligible))
    chosen = rng.sample(eligible, count)
    return [row.copy() for row in chosen]


def inject_near_duplicate(rows: list[dict], rate: float, rng: random.Random) -> list[dict]:
    eligible = [row for row in rows if row["transaction_id"] is not None]
    count = min(round(rate * len(rows)), len(eligible))
    chosen = rng.sample(eligible, count)
    new_rows = []
    for original in chosen:
        new_row = original.copy()
        if rng.random() < 0.5:
            alternatives = [status for status in STATUSES if status != original["status"]]
            new_row["status"] = rng.choice(alternatives)
        else:
            new_row["amount"] = f"{_parse_amount(original['amount']) + rng.uniform(1, 50):.2f}"
        moment = _parse_event_timestamp(original["event_timestamp"])
        bumped = moment + timedelta(minutes=rng.randint(1, 15))
        new_row["event_timestamp"] = bumped.strftime("%Y-%m-%dT%H:%M:%SZ")
        new_rows.append(new_row)
    return new_rows


def _apply_family_member(
    rows: list[dict],
    pool: list[int],
    rate: float,
    n_total: int,
    rng: random.Random,
    mutate_fn,
) -> int:
    target = min(round(rate * n_total), len(pool))
    chosen = rng.sample(pool, target)
    chosen_set = set(chosen)
    pool[:] = [i for i in pool if i not in chosen_set]
    sub_rows = [rows[i] for i in chosen]
    return mutate_fn(sub_rows, 1.0, rng)


def apply_defects(
    rows: list[dict], rates: DefectRates, seed: int, run_date: date
) -> tuple[list[dict], DefectReport]:
    rows_in = len(rows)
    working = list(rows)
    n = len(working)
    counts: dict[str, int] = {}

    rng = _defect_rng(seed, run_date, "late_event")
    counts["late_event"] = inject_late_event(
        working,
        rates.late_event,
        rng,
        min_days=rates.late_event_min_days,
        max_days=rates.late_event_max_days,
    )

    timestamp_pool = list(range(n))
    rng = _defect_rng(seed, run_date, "naive_timestamp")
    counts["naive_timestamp"] = _apply_family_member(
        working, timestamp_pool, rates.naive_timestamp, n, rng, inject_naive_timestamp
    )
    rng = _defect_rng(seed, run_date, "offset_timestamp")
    counts["offset_timestamp"] = _apply_family_member(
        working, timestamp_pool, rates.offset_timestamp, n, rng, inject_offset_timestamp
    )

    currency_pool = list(range(n))
    rng = _defect_rng(seed, run_date, "missing_currency")
    counts["missing_currency"] = _apply_family_member(
        working, currency_pool, rates.missing_currency, n, rng, inject_missing_currency
    )
    rng = _defect_rng(seed, run_date, "unknown_currency")
    counts["unknown_currency"] = _apply_family_member(
        working, currency_pool, rates.unknown_currency, n, rng, inject_unknown_currency
    )
    rng = _defect_rng(seed, run_date, "lowercase_currency")
    counts["lowercase_currency"] = _apply_family_member(
        working, currency_pool, rates.lowercase_currency, n, rng, inject_lowercase_currency
    )

    amount_pool = list(range(n))
    rng = _defect_rng(seed, run_date, "non_positive_amount")
    counts["non_positive_amount"] = _apply_family_member(
        working, amount_pool, rates.non_positive_amount, n, rng, inject_non_positive_amount
    )
    rng = _defect_rng(seed, run_date, "amount_formatting")
    counts["amount_formatting"] = _apply_family_member(
        working, amount_pool, rates.amount_formatting, n, rng, inject_amount_formatting
    )

    rng = _defect_rng(seed, run_date, "malformed_country")
    counts["malformed_country"] = inject_malformed_country(working, rates.malformed_country, rng)

    rng = _defect_rng(seed, run_date, "missing_transaction_id")
    counts["missing_transaction_id"] = inject_missing_transaction_id(
        working, rates.missing_transaction_id, rng
    )

    rng = _defect_rng(seed, run_date, "near_duplicate")
    near_dup_rows = inject_near_duplicate(working, rates.near_duplicate, rng)
    counts["near_duplicate"] = len(near_dup_rows)

    rng = _defect_rng(seed, run_date, "duplicate_exact")
    dup_rows = inject_duplicate_exact(working, rates.duplicate_exact, rng)
    counts["duplicate_exact"] = len(dup_rows)

    working = working + near_dup_rows + dup_rows

    rng = _defect_rng(seed, run_date, "shuffle")
    rng.shuffle(working)

    report = DefectReport(
        rows_in=rows_in,
        rows_out=len(working),
        counts={name: counts[name] for name in _CATALOG_ORDER},
    )
    return working, report
