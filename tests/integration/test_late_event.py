"""A transaction landed three days after it happened corrects a published day.

Builds three consecutive days, then lands a single extra row in a fourth
partition whose event happened on the first of those three days. The
expected EUR amount is computed from the exchange rate the harness itself
seeded, before the pipeline runs, using only currencies and a
(debtor_country, status) combination already present that day so no new
aggregate group is created.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import duckdb
import pytest

from payments.generator import build_daily_batch
from payments.generator.schema import validate_row
from payments.ingestion import land_batch

RUN_DATES: tuple[date, ...] = (date(2026, 4, 10), date(2026, 4, 11), date(2026, 4, 12))

# Mirrors conftest.py's FIXED_RATES for the currencies with 2 decimal-digit
# rates, so a round EUR target converts back to a clean native amount.
LATE_EVENT_RATES: dict[str, Decimal] = {
    "CAD": Decimal("1.6"),
    "CHF": Decimal("0.92"),
    "GBP": Decimal("0.87"),
    "MAD": Decimal("10.8"),
}

TARGET_AMOUNT_EUR = Decimal("100.00")


def _run_daily_dbt_chain(run_dbt, first_day: bool) -> None:
    if first_day:
        run_dbt("seed")
    run_dbt("build", "--select", "tag:staging")
    run_dbt("build", "--select", "tag:intermediate", "fct_transactions")
    run_dbt("build", "--select", "tag:marts", "--exclude", "fct_transactions")


def test_late_event_corrects_a_published_day(isolated_env, seeded_fx_rates, run_dbt) -> None:
    seeded_fx_rates(RUN_DATES[0], RUN_DATES[-1])

    for index, run_date in enumerate(RUN_DATES):
        rows, _report = build_daily_batch(run_date)
        land_batch(rows, run_date)
        _run_daily_dbt_chain(run_dbt, first_day=index == 0)

    event_date = RUN_DATES[0]
    injection_ingestion_date = event_date + timedelta(days=3)
    assert injection_ingestion_date - event_date == timedelta(days=3)
    assert injection_ingestion_date > RUN_DATES[-1]

    con = duckdb.connect(str(isolated_env.warehouse_path), read_only=True)
    try:
        currency_row = con.execute(
            "select currency_code from agg_fx_exposure_daily "
            "where event_date_utc = ? and currency_code in (?, ?, ?, ?) "
            "order by currency_code limit 1",
            [event_date, *LATE_EVENT_RATES],
        ).fetchone()
        assert currency_row is not None, (
            f"no existing agg_fx_exposure_daily group for {event_date} in a currency "
            f"with a known seeded rate ({sorted(LATE_EVENT_RATES)})"
        )
        currency = currency_row[0]
        rate = LATE_EVENT_RATES[currency]

        group_row = con.execute(
            "select debtor_country, status from agg_transactions_daily "
            "where event_date_utc = ? order by debtor_country, status limit 1",
            [event_date],
        ).fetchone()
        assert group_row is not None, f"no existing agg_transactions_daily group for {event_date}"
        debtor_country, status = group_row

        fct_count_before = con.execute("select count(*) from fct_transactions").fetchone()[0]
        agg_tx_group_before = con.execute(
            "select transaction_count, amount_eur_total from agg_transactions_daily "
            "where event_date_utc = ? and debtor_country = ? and status = ?",
            [event_date, debtor_country, status],
        ).fetchone()
        agg_tx_rowcount_before = con.execute(
            "select count(*) from agg_transactions_daily"
        ).fetchone()[0]
        agg_fx_rowcount_before = con.execute(
            "select count(*) from agg_fx_exposure_daily"
        ).fetchone()[0]
        dq_rowcount_before = con.execute("select count(*) from data_quality_daily").fetchone()[0]
    finally:
        con.close()

    injected_native_amount = (TARGET_AMOUNT_EUR * rate).quantize(Decimal("0.01"))
    predicted_amount_eur = (injected_native_amount / rate).quantize(Decimal("0.01"))
    assert predicted_amount_eur == TARGET_AMOUNT_EUR

    creditor_country = "DE" if debtor_country != "DE" else "FR"
    event_timestamp = datetime(
        event_date.year, event_date.month, event_date.day, 12, 0, 0, tzinfo=UTC
    )
    late_row = {
        "transaction_id": "TXN-LATE-EVENT-0001",
        "event_timestamp": event_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "amount": str(injected_native_amount),
        "currency": currency,
        "debtor_account": "FRLATEEVENTDEBTORACCOUNT01",
        "creditor_account": "DELATEEVENTCREDITORACCOUNT01",
        "debtor_country": debtor_country,
        "creditor_country": creditor_country,
        "status": status,
        "rejection_reason": None,
        "channel": "ONLINE",
        "source_batch_id": "BATCH-LATE-EVENT",
        "ingested_at": datetime.now(UTC),
        "ingestion_date": injection_ingestion_date,
    }
    validate_row(late_row)
    land_batch([late_row], injection_ingestion_date)
    _run_daily_dbt_chain(run_dbt, first_day=False)

    con = duckdb.connect(str(isolated_env.warehouse_path), read_only=True)
    try:
        fct_count_after = con.execute("select count(*) from fct_transactions").fetchone()[0]
        assert fct_count_after == fct_count_before + 1, (
            f"fct_transactions row count: expected {fct_count_before + 1}, "
            f"observed {fct_count_after}"
        )

        agg_tx_group_after = con.execute(
            "select transaction_count, amount_eur_total from agg_transactions_daily "
            "where event_date_utc = ? and debtor_country = ? and status = ?",
            [event_date, debtor_country, status],
        ).fetchone()
        assert agg_tx_group_after is not None, (
            f"agg_transactions_daily group for {event_date}/{debtor_country}/{status} disappeared"
        )
        count_before, amount_before = agg_tx_group_before
        count_after, amount_after = agg_tx_group_after
        assert count_after == count_before + 1, (
            f"agg_transactions_daily transaction_count for {event_date}/{debtor_country}/{status}: "
            f"expected {count_before + 1}, observed {count_after}"
        )
        expected_amount_after = float(amount_before) + float(predicted_amount_eur)
        assert abs(float(amount_after) - expected_amount_after) < 0.005, (
            f"agg_transactions_daily amount_eur_total for {event_date}/{debtor_country}/{status}: "
            f"expected {expected_amount_after} (= {amount_before} + {predicted_amount_eur}), "
            f"observed {amount_after}"
        )

        agg_tx_rowcount_after = con.execute(
            "select count(*) from agg_transactions_daily"
        ).fetchone()[0]
        assert agg_tx_rowcount_after == agg_tx_rowcount_before, (
            f"agg_transactions_daily group count changed: expected {agg_tx_rowcount_before}, "
            f"observed {agg_tx_rowcount_after}"
        )
        agg_fx_rowcount_after = con.execute(
            "select count(*) from agg_fx_exposure_daily"
        ).fetchone()[0]
        assert agg_fx_rowcount_after == agg_fx_rowcount_before, (
            f"agg_fx_exposure_daily group count changed: expected {agg_fx_rowcount_before}, "
            f"observed {agg_fx_rowcount_after}"
        )

        stray_tx_rows = con.execute(
            "select count(*) from agg_transactions_daily where event_date_utc = ?",
            [injection_ingestion_date],
        ).fetchone()[0]
        assert stray_tx_rows == 0, (
            f"agg_transactions_daily has {stray_tx_rows} row(s) with event_date_utc equal to "
            f"the injected partition's ingestion date {injection_ingestion_date}, expected 0"
        )
        stray_fx_rows = con.execute(
            "select count(*) from agg_fx_exposure_daily where event_date_utc = ?",
            [injection_ingestion_date],
        ).fetchone()[0]
        assert stray_fx_rows == 0, (
            f"agg_fx_exposure_daily has {stray_fx_rows} row(s) with event_date_utc equal to "
            f"the injected partition's ingestion date {injection_ingestion_date}, expected 0"
        )

        dq_rowcount_after = con.execute("select count(*) from data_quality_daily").fetchone()[0]
        assert dq_rowcount_after == dq_rowcount_before + 1, (
            f"data_quality_daily row count: expected {dq_rowcount_before + 1}, "
            f"observed {dq_rowcount_after}"
        )
        dq_new_row = con.execute(
            "select count(*) from data_quality_daily where ingestion_date = ?",
            [injection_ingestion_date],
        ).fetchone()[0]
        assert dq_new_row == 1, (
            f"data_quality_daily row for ingestion_date {injection_ingestion_date}: "
            f"expected 1, observed {dq_new_row}"
        )

        print(
            "predicted_amount_eur",
            predicted_amount_eur,
            "observed_amount_after",
            amount_after,
            "observed_amount_before",
            amount_before,
        )
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
