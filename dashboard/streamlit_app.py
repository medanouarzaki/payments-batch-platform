"""Public entry point: renders the dashboard from the committed CSV snapshot.

Unlike app.py, this script takes no command-line arguments and reads no
environment variables: it only depends on the CSV files and manifest
committed under dashboard/snapshot/, resolved relative to this file's own
location, so it can run standalone from a checkout that never sees the
internal warehouse or serving file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app  # noqa: E402
from snapshot_loader import build_database_from_snapshot  # noqa: E402

_SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshot"


def snapshot_published_at(snapshot_dir: Path) -> str:
    """Return the publication timestamp recorded in a snapshot manifest.

    This page reads committed CSV files rather than the warehouse, and nothing
    refreshes them on its own, so the moment those tables were published belongs
    on the page next to the numbers they produce.
    """
    manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    return str(manifest["serving_published_at"])


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
    st.caption(
        f"Snapshot published {snapshot_published_at(_SNAPSHOT_DIR)}. This page reads CSV "
        "files committed to the repository, not the live warehouse, and refreshing them "
        "is a manual step."
    )


if __name__ == "__main__":
    main()
