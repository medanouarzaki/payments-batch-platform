"""Entry point for the payments dashboard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from views import volumes  # noqa: E402

import data  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serving-path", required=True)
    args = parser.parse_args()

    mtime_ns = data.serving_mtime_ns(args.serving_path)

    st.title("Payments dashboard")

    quality = data.load_data_quality(args.serving_path, mtime_ns)
    latest_ingestion = quality["ingestion_date"].max()
    st.caption(f"Latest ingestion date: {latest_ingestion}")

    daily = data.load_daily_volumes(args.serving_path, mtime_ns)
    countries = data.load_countries(args.serving_path, mtime_ns)
    volumes.render(daily, countries)


if __name__ == "__main__":
    main()
