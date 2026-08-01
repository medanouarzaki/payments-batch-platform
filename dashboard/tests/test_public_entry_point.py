"""Public entry point: reconstruction fidelity, argument-free rendering, isolation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import duckdb
from streamlit.testing.v1 import AppTest

_DASHBOARD_DIR = Path(__file__).resolve().parents[1]
_SNAPSHOT_DIR = _DASHBOARD_DIR / "snapshot"
_STREAMLIT_APP_PATH = str(_DASHBOARD_DIR / "streamlit_app.py")

_SNAPSHOT_LOADER_PATH = _DASHBOARD_DIR / "snapshot_loader.py"
_SPEC = importlib.util.spec_from_file_location("dashboard_snapshot_loader", _SNAPSHOT_LOADER_PATH)
snapshot_loader = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(snapshot_loader)

EXPECTED_ROWS = {
    "agg_fx_exposure_daily": 1107,
    "agg_transactions_channel_daily": 1841,
    "agg_transactions_daily": 4394,
    "data_quality_daily": 118,
    "dim_country": 11,
    "dim_currency": 9,
}


def test_reconstruction_matches_the_manifests_tables_rows_and_types() -> None:
    manifest = json.loads((_SNAPSHOT_DIR / "manifest.json").read_text())
    manifest_by_name = {entry["name"]: entry for entry in manifest["tables"]}
    assert set(manifest_by_name) == set(EXPECTED_ROWS)

    database_path = snapshot_loader.build_database_from_snapshot(_SNAPSHOT_DIR)
    con = duckdb.connect(str(database_path), read_only=True)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "select table_name from information_schema.tables where table_schema = 'main'"
            ).fetchall()
        }
        assert tables == set(EXPECTED_ROWS)

        for name, expected_rows in EXPECTED_ROWS.items():
            entry = manifest_by_name[name]

            rows = con.execute(f'select count(*) from "{name}"').fetchone()[0]
            assert rows == expected_rows
            assert rows == entry["rows"]

            columns = con.execute(
                "select column_name, data_type from information_schema.columns "
                "where table_name = ? order by ordinal_position",
                [name],
            ).fetchall()
            expected_columns = [(column["name"], column["type"]) for column in entry["columns"]]
            assert columns == expected_columns
    finally:
        con.close()


def test_streamlit_app_renders_four_tabs_without_any_argument() -> None:
    app = AppTest.from_file(_STREAMLIT_APP_PATH, default_timeout=60)
    app.run()

    assert len(app.exception) == 0
    assert len(app.tabs) == 4
    for tab in app.tabs:
        assert len(tab.get("dataframe")) + len(tab.get("metric")) > 0


def test_entry_point_never_writes_under_the_snapshot_directory() -> None:
    before = sorted(str(path.relative_to(_SNAPSHOT_DIR)) for path in _SNAPSHOT_DIR.rglob("*"))

    database_path = snapshot_loader.build_database_from_snapshot(_SNAPSHOT_DIR)

    after = sorted(str(path.relative_to(_SNAPSHOT_DIR)) for path in _SNAPSHOT_DIR.rglob("*"))
    assert before == after

    repo_root = _DASHBOARD_DIR.parent
    assert repo_root not in database_path.parents
