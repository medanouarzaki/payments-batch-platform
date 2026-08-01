"""Public entry point: renders the dashboard from the committed CSV snapshot.

Unlike app.py, this script takes no command-line arguments and reads no
environment variables: it only depends on the CSV files and manifest
committed under dashboard/snapshot/, resolved relative to this file's own
location, so it can run standalone from a checkout that never sees the
internal warehouse or serving file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app  # noqa: E402
from snapshot_loader import build_database_from_snapshot  # noqa: E402

_SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshot"


@st.cache_resource
def _reconstructed_serving_path() -> str:
    return str(build_database_from_snapshot(_SNAPSHOT_DIR))


def main() -> None:
    try:
        serving_path = _reconstructed_serving_path()
    except FileNotFoundError as exc:
        st.title("Payments dashboard")
        st.error(str(exc))
        return

    app.render(serving_path)


if __name__ == "__main__":
    main()
