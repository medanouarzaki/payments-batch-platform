"""View 1: daily transaction volumes and EUR amounts, by day and by country."""

from __future__ import annotations

import pandas as pd
import streamlit as st

UNKNOWN_COUNTRY_LABEL = "unknown"


def render(daily: pd.DataFrame, countries: pd.DataFrame) -> None:
    """Render volumes and EUR amounts by day and by country.

    daily and countries are pre-loaded pandas frames; this function opens no
    connection of its own.
    """
    st.header("Daily volumes")

    event_dates = daily["event_date_utc"].dt.date
    min_date = event_dates.min()
    max_date = event_dates.max()
    start_date, end_date = st.slider(
        "Date range",
        min_value=min_date,
        max_value=max_date,
        value=(min_date, max_date),
    )

    mask = (event_dates >= start_date) & (event_dates <= end_date)
    filtered = daily.loc[mask]

    by_day = (
        filtered.groupby("event_date_utc")[["transaction_count", "amount_eur_total"]]
        .sum()
        .sort_index()
        .reset_index()
    )
    by_day["event_date_utc"] = by_day["event_date_utc"].dt.date
    st.subheader("By day")
    st.dataframe(by_day, hide_index=True)

    # Left join: every row of filtered is kept, including the one whose
    # debtor_country is null. The missing country_name is only replaced with
    # an explicit label for display, never in the underlying data.
    joined = filtered.merge(countries, left_on="debtor_country", right_on="alpha_2", how="left")
    joined = joined.assign(country_label=joined["country_name"].fillna(UNKNOWN_COUNTRY_LABEL))

    by_country = (
        joined.groupby("country_label")[["transaction_count", "amount_eur_total"]]
        .sum()
        .sort_index()
        .reset_index()
    )
    st.subheader("By country")
    st.dataframe(by_country, hide_index=True)
