"""Deterministic synthetic transaction batch generator."""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, date, datetime

from payments.config import get_settings
from payments.generator.schema import (
    CHANNELS,
    COUNTRIES,
    CURRENCIES,
    IBAN_LENGTHS,
    RAW_COLUMNS,
    REJECTION_REASONS,
    STATUSES,
    validate_row,
)

_WEEKDAY_FACTOR = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.55, 6: 0.40}

_PEAK_HOURS = frozenset(range(8, 20))


def derive_seed(seed: int, run_date: date) -> int:
    digest = hashlib.sha256(f"{seed}:{run_date.isoformat()}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def rows_for_weekday(run_date: date, rows_min: int, rows_max: int, rng: random.Random) -> int:
    factor = _WEEKDAY_FACTOR[run_date.weekday()]
    base = rng.randint(rows_min, rows_max)
    return max(1, int(base * factor))


def _iban_check_digits(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    numeric = "".join(
        ch if ch.isdigit() else str(ord(ch.upper()) - ord("A") + 10) for ch in rearranged
    )
    remainder = int(numeric) % 97
    return f"{98 - remainder:02d}"


def _generate_iban(rng: random.Random, country: str) -> str:
    if country not in IBAN_LENGTHS:
        raise ValueError(f"no IBAN length known for country {country!r}")
    bban_length = IBAN_LENGTHS[country] - 4
    bban = "".join(str(rng.randint(0, 9)) for _ in range(bban_length))
    check_digits = _iban_check_digits(country, bban)
    return f"{country}{check_digits}{bban}"


def _generate_event_timestamp(run_date: date, rng: random.Random) -> str:
    weights = [5 if hour in _PEAK_HOURS else 1 for hour in range(24)]
    hour = rng.choices(range(24), weights=weights)[0]
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    moment = datetime(run_date.year, run_date.month, run_date.day, hour, minute, second, tzinfo=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_amount(rng: random.Random) -> str:
    amount = rng.lognormvariate(3.2, 1.1)
    return f"{amount:.2f}"


def batch_fingerprint(rows: list[dict]) -> str:
    hasher = hashlib.sha256()
    for row in rows:
        for column in RAW_COLUMNS:
            value = row[column]
            if isinstance(value, datetime):
                text = value.astimezone(UTC).isoformat()
            elif isinstance(value, date):
                text = value.isoformat()
            else:
                text = str(value)
            hasher.update(text.encode())
            hasher.update(b"\x1f")
        hasher.update(b"\x1e")
    return hasher.hexdigest()


def generate_batch(
    run_date: date, n_rows: int | None = None, seed: int | None = None
) -> list[dict]:
    settings = get_settings()
    if seed is None:
        seed = settings.generator_seed

    rng = random.Random(derive_seed(seed, run_date))

    if n_rows is None:
        n_rows = rows_for_weekday(run_date, settings.rows_min, settings.rows_max, rng)

    source_batch_id = f"BATCH-{run_date:%Y%m%d}-01"
    ingested_at = datetime(run_date.year, run_date.month, run_date.day, 23, 59, 59, tzinfo=UTC)

    transaction_numbers = rng.sample(range(10**8), n_rows)

    rows: list[dict] = []
    for index in range(n_rows):
        transaction_id = f"TXN-{run_date.isoformat()}-{transaction_numbers[index]:08d}"

        debtor_country = rng.choice(COUNTRIES)
        creditor_country = rng.choice(COUNTRIES)
        debtor_account = _generate_iban(rng, debtor_country)
        creditor_account = _generate_iban(rng, creditor_country)
        while creditor_account == debtor_account:
            creditor_country = rng.choice(COUNTRIES)
            creditor_account = _generate_iban(rng, creditor_country)

        status = rng.choices(STATUSES, weights=[88, 8, 4])[0]
        rejection_reason = rng.choice(REJECTION_REASONS) if status == "REJECTED" else None

        row = {
            "transaction_id": transaction_id,
            "event_timestamp": _generate_event_timestamp(run_date, rng),
            "amount": _generate_amount(rng),
            "currency": rng.choices(CURRENCIES, weights=[40, 10, 10, 8, 6, 6, 6, 6, 8])[0],
            "debtor_account": debtor_account,
            "creditor_account": creditor_account,
            "debtor_country": debtor_country,
            "creditor_country": creditor_country,
            "status": status,
            "rejection_reason": rejection_reason,
            "channel": rng.choice(CHANNELS),
            "source_batch_id": source_batch_id,
            "ingested_at": ingested_at,
            "ingestion_date": run_date,
        }
        validate_row(row)
        rows.append(row)

    return rows
