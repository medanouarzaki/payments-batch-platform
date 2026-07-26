from datetime import UTC, date, datetime

import pytest

from payments.generator.schema import (
    METADATA_COLUMNS,
    RAW_COLUMNS,
    STRING_COLUMNS,
    SchemaError,
    validate_row,
)


def _valid_row() -> dict[str, object]:
    return {
        "transaction_id": "TXN-2026-07-26-00000001",
        "event_timestamp": "2026-07-26T10:00:00Z",
        "amount": "42.50",
        "currency": "EUR",
        "debtor_account": "FR7630006000011234567890189",
        "creditor_account": "DE89370400440532013000",
        "debtor_country": "FR",
        "creditor_country": "DE",
        "status": "ACCEPTED",
        "rejection_reason": None,
        "channel": "ONLINE",
        "source_batch_id": "BATCH-20260726-01",
        "ingested_at": datetime(2026, 7, 26, 23, 59, 59, tzinfo=UTC),
        "ingestion_date": date(2026, 7, 26),
    }


def test_raw_columns_has_fourteen_unique_names():
    assert len(RAW_COLUMNS) == 14
    assert len(set(RAW_COLUMNS)) == 14


def test_string_and_metadata_columns_union_equals_raw_columns():
    assert STRING_COLUMNS | METADATA_COLUMNS == set(RAW_COLUMNS)
    assert STRING_COLUMNS.isdisjoint(METADATA_COLUMNS)


def test_validate_row_accepts_correct_row():
    validate_row(_valid_row())


def test_validate_row_rejects_missing_key():
    row = _valid_row()
    del row["channel"]
    with pytest.raises(SchemaError):
        validate_row(row)


def test_validate_row_rejects_extra_key():
    row = _valid_row()
    row["extra_field"] = "oops"
    with pytest.raises(SchemaError):
        validate_row(row)


def test_validate_row_rejects_float_amount():
    row = _valid_row()
    row["amount"] = 42.50
    with pytest.raises(SchemaError):
        validate_row(row)


def test_validate_row_rejects_naive_ingested_at():
    row = _valid_row()
    row["ingested_at"] = datetime(2026, 7, 26, 23, 59, 59)
    with pytest.raises(SchemaError):
        validate_row(row)


def test_validate_row_rejects_string_ingestion_date():
    row = _valid_row()
    row["ingestion_date"] = "2026-07-26"
    with pytest.raises(SchemaError):
        validate_row(row)
