"""View 3: FX exposure by currency, with a visible flag for carried-forward rates."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render(fx: pd.DataFrame, currencies: pd.DataFrame) -> None:
    """Render exposure by currency and flag rows using a carried-forward rate.

    fx and currencies are pre-loaded pandas frames; this function opens no
    connection. The join on currencies is a left join, so every fx row is
    kept even if a currency label is unavailable.
    """
    st.header("FX exposure")

    joined = fx.merge(currencies, on="currency_code", how="left")

    carried = joined.loc[joined["is_carried_forward"]]
    if len(carried) > 0:
        st.warning(
            f"{len(carried)} rows use a carried-forward exchange rate "
            f"({int(carried['transaction_count'].sum())} transactions affected)."
        )
        st.subheader("Carried-forward rate rows")
        st.dataframe(carried)
    else:
        st.success("No row uses a carried-forward exchange rate.")

    st.subheader("Exposure by currency")
    by_currency = (
        joined.groupby("currency_code")[["transaction_count", "amount_eur_total"]]
        .sum()
        .sort_index()
    )
    st.dataframe(by_currency)
