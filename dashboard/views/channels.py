"""View 2: rejection rate by channel, in aggregate and over time."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render(channel: pd.DataFrame) -> None:
    """Render the overall and daily rejection rate per channel.

    channel is a pre-loaded pandas frame; this function opens no connection.
    """
    st.header("Rejections by channel")

    totals = channel.groupby("channel")["transaction_count"].sum()
    rejected = (
        channel.loc[channel["status"] == "REJECTED"].groupby("channel")["transaction_count"].sum()
    )
    summary = pd.DataFrame({"transaction_count": totals}).assign(
        rejected=rejected.reindex(totals.index).fillna(0)
    )
    summary["rejection_rate"] = summary["rejected"] / summary["transaction_count"]

    st.subheader("Overall rejection rate")
    st.dataframe(summary.sort_index())

    st.subheader("Rejection rate over time")
    by_day = channel.groupby(["event_date_utc", "channel"])["transaction_count"].sum()
    rejected_by_day = (
        channel.loc[channel["status"] == "REJECTED"]
        .groupby(["event_date_utc", "channel"])["transaction_count"]
        .sum()
    )
    daily = pd.DataFrame({"transaction_count": by_day}).assign(
        rejected=rejected_by_day.reindex(by_day.index).fillna(0)
    )
    daily["rejection_rate"] = daily["rejected"] / daily["transaction_count"]
    pivot = daily["rejection_rate"].unstack("channel")
    st.line_chart(pivot)
