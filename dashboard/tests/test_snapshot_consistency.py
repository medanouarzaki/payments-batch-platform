"""Snapshot consistency: the two carried-forward formulations, and the publication date."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

_DASHBOARD_DIR = Path(__file__).resolve().parents[1]
_SNAPSHOT_DIR = _DASHBOARD_DIR / "snapshot"
_STREAMLIT_APP_PATH = str(_DASHBOARD_DIR / "streamlit_app.py")

_LOADERS_PATH = _DASHBOARD_DIR / "loaders.py"
_SPEC = importlib.util.spec_from_file_location("dashboard_loaders", _LOADERS_PATH)
loaders = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(loaders)

_SNAPSHOT_LOADER_PATH = _DASHBOARD_DIR / "snapshot_loader.py"
_SNAPSHOT_LOADER_SPEC = importlib.util.spec_from_file_location(
    "dashboard_snapshot_loader", _SNAPSHOT_LOADER_PATH
)
snapshot_loader = importlib.util.module_from_spec(_SNAPSHOT_LOADER_SPEC)
_SNAPSHOT_LOADER_SPEC.loader.exec_module(snapshot_loader)

_STREAMLIT_APP_SPEC = importlib.util.spec_from_file_location(
    "dashboard_streamlit_app", _STREAMLIT_APP_PATH
)
streamlit_app = importlib.util.module_from_spec(_STREAMLIT_APP_SPEC)
_STREAMLIT_APP_SPEC.loader.exec_module(streamlit_app)

EXPECTED_CARRIED_FORWARD_ROWS = 259
EXPECTED_CARRIED_FORWARD_TRANSACTIONS = 348526


def test_is_carried_forward_and_fx_status_select_the_same_transactions() -> None:
    """Both formulations of "carried forward" must pick out the same rows.

    The reconstruction goes through build_database_from_snapshot and loaders.py,
    the same path the public entry point uses to render the exposure view.
    """
    database_path = snapshot_loader.build_database_from_snapshot(_SNAPSHOT_DIR)
    mtime_ns = loaders.serving_mtime_ns(str(database_path))
    fx = loaders.load_fx_exposure(str(database_path), mtime_ns)

    flagged = fx.loc[fx["is_carried_forward"]]
    by_status = fx.loc[fx["fx_status"] == "carried_forward"]

    assert len(flagged) == EXPECTED_CARRIED_FORWARD_ROWS
    assert int(flagged["transaction_count"].sum()) == EXPECTED_CARRIED_FORWARD_TRANSACTIONS
    assert len(by_status) == EXPECTED_CARRIED_FORWARD_ROWS
    assert int(by_status["transaction_count"].sum()) == EXPECTED_CARRIED_FORWARD_TRANSACTIONS


def test_snapshot_published_at_reads_the_manifest_field(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"serving_published_at": "2026-08-01T22:43:14Z"}))

    assert streamlit_app.snapshot_published_at(tmp_path) == "2026-08-01T22:43:14Z"


def test_public_entry_point_caption_shows_the_snapshot_publication_date() -> None:
    expected = streamlit_app.snapshot_published_at(_SNAPSHOT_DIR)

    app = AppTest.from_file(_STREAMLIT_APP_PATH, default_timeout=60)
    app.run()

    matching_captions = [c.value for c in app.caption if expected in c.value]
    assert len(matching_captions) == 1
