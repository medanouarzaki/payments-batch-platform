"""Single declaration of the raw transactions source contract."""

from __future__ import annotations

from datetime import date, datetime

RAW_COLUMNS: tuple[str, ...] = (
    "transaction_id",
    "event_timestamp",
    "amount",
    "currency",
    "debtor_account",
    "creditor_account",
    "debtor_country",
    "creditor_country",
    "status",
    "rejection_reason",
    "channel",
    "source_batch_id",
    "ingested_at",
    "ingestion_date",
)

METADATA_COLUMNS: frozenset[str] = frozenset({"ingested_at", "ingestion_date"})

STRING_COLUMNS: frozenset[str] = frozenset(RAW_COLUMNS) - METADATA_COLUMNS

STATUSES: tuple[str, ...] = ("ACCEPTED", "REJECTED", "PENDING")

CHANNELS: tuple[str, ...] = ("ONLINE", "POS", "ATM", "TRANSFER", "MOBILE")

REJECTION_REASONS: tuple[str, ...] = (
    "INSUFFICIENT_FUNDS",
    "ACCOUNT_CLOSED",
    "INVALID_ACCOUNT",
    "LIMIT_EXCEEDED",
    "SUSPECTED_FRAUD",
)

CURRENCIES: tuple[str, ...] = ("EUR", "USD", "GBP", "CHF", "SEK", "PLN", "JPY", "CAD", "MAD")

COUNTRIES: tuple[str, ...] = (
    "FR",
    "DE",
    "ES",
    "IT",
    "NL",
    "BE",
    "GB",
    "CH",
    "SE",
    "PL",
    "MA",
)

IBAN_LENGTHS: dict[str, int] = {
    "FR": 27,
    "DE": 22,
    "ES": 24,
    "IT": 27,
    "NL": 18,
    "BE": 16,
    "GB": 22,
    "CH": 21,
    "SE": 24,
    "PL": 28,
    "MA": 28,
}


class SchemaError(Exception):
    """Raised when a row does not conform to the raw transactions contract."""


def validate_row(row: dict[str, object]) -> None:
    row_keys = set(row.keys())
    expected_keys = set(RAW_COLUMNS)
    if row_keys != expected_keys:
        missing = expected_keys - row_keys
        extra = row_keys - expected_keys
        raise SchemaError(
            f"row keys do not match RAW_COLUMNS: missing={sorted(missing)}, extra={sorted(extra)}"
        )

    for column in STRING_COLUMNS:
        value = row[column]
        if value is not None and not isinstance(value, str):
            raise SchemaError(f"column '{column}' must be a str, got {type(value).__name__}")

    ingested_at = row["ingested_at"]
    if not isinstance(ingested_at, datetime) or ingested_at.tzinfo is None:
        raise SchemaError("column 'ingested_at' must be a timezone-aware datetime in UTC")
    if ingested_at.utcoffset().total_seconds() != 0:
        raise SchemaError("column 'ingested_at' must carry a UTC offset")

    ingestion_date = row["ingestion_date"]
    if not isinstance(ingestion_date, date) or isinstance(ingestion_date, datetime):
        raise SchemaError("column 'ingestion_date' must be a date")
