"""View 4: data quality panel -- quarantine reasons, lateness, duplicates, degraded days."""

from __future__ import annotations

import pandas as pd
import streamlit as st

# A day is considered "degraded" when its rejection_rate exceeds 2% (0.02).
# The sample data shows daily rejection rates in the roughly 0.8%-1.1% range,
# so this threshold is well above routine noise and flags a genuine outlier
# rather than ordinary day-to-day variation.
DEGRADED_REJECTION_RATE_THRESHOLD = 0.02

QUARANTINE_REASON_COLUMNS = (
    "quarantined_missing_key_count",
    "quarantined_missing_currency_count",
    "quarantined_unknown_currency_count",
    "quarantined_non_positive_amount_count",
    "quarantined_invalid_amount_count",
    "quarantined_invalid_timestamp_count",
)


def render(quality: pd.DataFrame) -> None:
    """Render the four quality indicator families.

    quality is a pre-loaded pandas frame; this function opens no connection.
    Every quarantine reason column is shown, including those summing to zero.
    """
    st.header("Data quality")

    st.subheader("Quarantine by reason")
    reasons = quality[list(QUARANTINE_REASON_COLUMNS)].sum()
    st.dataframe(reasons)

    st.subheader("Lateness and duplicates")
    st.metric("Late rows", int(quality["late_row_count"].sum()))
    st.metric("Duplicates removed", int(quality["duplicate_removed_count"].sum()))

    st.subheader("Degraded days")
    degraded = quality.loc[quality["rejection_rate"] > DEGRADED_REJECTION_RATE_THRESHOLD]
    st.metric("Degraded days", len(degraded))
    st.dataframe(degraded)
