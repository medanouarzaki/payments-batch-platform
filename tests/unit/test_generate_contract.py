from datetime import UTC, date, datetime

from payments.generator import generate_batch
from payments.generator.schema import CURRENCIES, RAW_COLUMNS, validate_row


def _iban_mod97_ok(iban: str) -> bool:
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(
        ch if ch.isdigit() else str(ord(ch.upper()) - ord("A") + 10) for ch in rearranged
    )
    return int(numeric) % 97 == 1


def test_all_rows_pass_validate_row_and_have_columns_in_order():
    rows = generate_batch(date(2026, 7, 21), n_rows=3000, seed=1)
    for row in rows:
        validate_row(row)
        assert list(row.keys()) == list(RAW_COLUMNS)


def test_transaction_ids_are_unique_and_non_null():
    rows = generate_batch(date(2026, 7, 21), n_rows=3000, seed=1)
    ids = [row["transaction_id"] for row in rows]
    assert all(tid for tid in ids)
    assert len(set(ids)) == len(ids)


def test_currencies_are_valid_and_uppercase():
    rows = generate_batch(date(2026, 7, 21), n_rows=3000, seed=1)
    for row in rows:
        assert row["currency"] in CURRENCIES
        assert row["currency"] == row["currency"].upper()


def test_amounts_convert_to_strictly_positive_float():
    rows = generate_batch(date(2026, 7, 21), n_rows=3000, seed=1)
    for row in rows:
        assert float(row["amount"]) > 0


def test_event_timestamps_are_utc_and_on_run_date():
    run_date = date(2026, 7, 21)
    rows = generate_batch(run_date, n_rows=3000, seed=1)
    for row in rows:
        raw = row["event_timestamp"]
        assert raw.endswith("Z")
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == UTC.utcoffset(None)
        assert parsed.date() == run_date


def test_rejection_reason_present_iff_status_rejected():
    rows = generate_batch(date(2026, 7, 21), n_rows=3000, seed=1)
    statuses_seen = {row["status"] for row in rows}
    assert statuses_seen == {"ACCEPTED", "REJECTED", "PENDING"}
    for row in rows:
        if row["status"] == "REJECTED":
            assert row["rejection_reason"] is not None
        else:
            assert row["rejection_reason"] is None


def test_all_ibans_pass_mod97_checksum():
    rows = generate_batch(date(2026, 7, 21), n_rows=3000, seed=1)
    for row in rows:
        assert _iban_mod97_ok(row["debtor_account"])
        assert _iban_mod97_ok(row["creditor_account"])


def test_debtor_and_creditor_accounts_differ():
    rows = generate_batch(date(2026, 7, 21), n_rows=3000, seed=1)
    for row in rows:
        assert row["debtor_account"] != row["creditor_account"]


def test_volume_varies_by_weekday_within_bounds():
    from payments.config import get_settings

    settings = get_settings()
    # 2026-07-20 is a Monday: Mon=20, Tue=21, Sat=25, Sun=26 of the same week.
    tuesday = generate_batch(date(2026, 7, 21), seed=7)
    saturday = generate_batch(date(2026, 7, 25), seed=7)
    sunday = generate_batch(date(2026, 7, 26), seed=7)

    assert len(sunday) < len(saturday) < len(tuesday)

    lower_bound = settings.rows_min * 0.40
    for batch in (tuesday, saturday, sunday):
        assert lower_bound <= len(batch) <= settings.rows_max
