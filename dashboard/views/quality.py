"""View 4: data quality panel -- quarantine reasons, lateness, duplicates, degraded days."""

from __future__ import annotations

import pandas as pd
import streamlit as st

QUARANTINE_REASON_COLUMNS = (
    "quarantined_missing_key_count",
    "quarantined_missing_currency_count",
    "quarantined_unknown_currency_count",
    "quarantined_non_positive_amount_count",
    "quarantined_invalid_amount_count",
    "quarantined_invalid_timestamp_count",
)


def render(quality_data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    """Render the four quality indicator families.

    quality_data is (quality, degraded): two pre-loaded pandas frames on two
    different date axes, never joined here. quality is keyed by
    ingestion_date. degraded is keyed by event_date_utc. Every quarantine
    reason column is shown, including those summing to zero.
    """
    quality, degraded = quality_data
    st.header("Data quality")

    st.subheader("Quarantine by reason")
    reasons = quality[list(QUARANTINE_REASON_COLUMNS)].sum()
    reasons_display = reasons.rename_axis("reason").reset_index(name="quarantined_count")
    st.dataframe(reasons_display, hide_index=True)

    reasons_sum = int(reasons.sum())
    quarantined_total = int(quality["quarantined_row_count"].sum())
    gap = reasons_sum - quarantined_total
    st.caption(
        f"Sum of reasons ({reasons_sum}) vs quarantined_row_count "
        f"({quarantined_total}): a gap of {gap}. The gap is the count of extra "
        "reasons carried by rows that trigger more than one at once. On the "
        "warehouse behind this snapshot, 95 rows carry exactly two reasons, none "
        "carries three, and they fall on 65 of the 118 ingestion dates. A dbt "
        "test checks that identity day by day; this page cannot, because the "
        "quarantine table is not part of the published snapshot."
    )

    st.subheader("Lateness and duplicates")
    st.metric("Late rows", int(quality["late_row_count"].sum()))
    st.metric("Duplicates removed", int(quality["duplicate_removed_count"].sum()))

    # A day (on the event_date_utc axis of agg_fx_exposure_daily) is
    # considered "degraded" when at least one row used a carried-forward
    # exchange rate, or at least one row has no rate at all (fx_status =
    # rate_missing). Measured at the lot 6.8 audit: 40 of 123 event dates
    # qualify under this union, versus 35 for carried-forward alone and 5
    # for missing-rate alone -- the union is the most inclusive of the three
    # candidate definitions that each qualify a strictly positive, strictly
    # partial subset of days.
    st.subheader("Degraded days (FX conversion)")
    st.metric("Degraded days", len(degraded))
    degraded_display = degraded.assign(event_date_utc=degraded["event_date_utc"].dt.date)
    st.dataframe(degraded_display, hide_index=True)
