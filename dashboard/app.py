"""Entry point for the payments dashboard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders  # noqa: E402
from views import channels, exposure, quality, volumes  # noqa: E402


def render(serving_path: str) -> None:
    st.title("Payments dashboard")

    try:
        mtime_ns = loaders.serving_mtime_ns(serving_path)
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    quality_data = loaders.load_data_quality(serving_path, mtime_ns)
    quality_frame, _ = quality_data
    latest_ingestion = quality_frame["ingestion_date"].max().date()
    st.caption(f"Latest ingestion date: {latest_ingestion}")

    daily = loaders.load_daily_volumes(serving_path, mtime_ns)
    countries = loaders.load_countries(serving_path, mtime_ns)
    channel_frame = loaders.load_channel_rejections(serving_path, mtime_ns)
    fx_frame = loaders.load_fx_exposure(serving_path, mtime_ns)
    currency_frame = loaders.load_currencies(serving_path, mtime_ns)

    tab_volumes, tab_channels, tab_exposure, tab_quality = st.tabs(
        ["Volumes", "Channels", "FX exposure", "Data quality"]
    )
    with tab_volumes:
        volumes.render(daily, countries)
    with tab_channels:
        channels.render(channel_frame)
    with tab_exposure:
        exposure.render(fx_frame, currency_frame)
    with tab_quality:
        quality.render(quality_data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serving-path", required=True)
    args = parser.parse_args()
    render(args.serving_path)


if __name__ == "__main__":
    main()
