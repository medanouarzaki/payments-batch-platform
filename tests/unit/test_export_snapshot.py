"""export_snapshot: CSV round-trip fidelity, idempotence, and manifest accuracy."""

from __future__ import annotations

import json

import duckdb

from payments.publish.export_snapshot import export_snapshot
from payments.publish.fingerprint import table_fingerprint

SNAPSHOT_TABLES: tuple[str, ...] = (
    "agg_transactions_daily",
    "agg_transactions_channel_daily",
    "agg_fx_exposure_daily",
    "data_quality_daily",
    "dim_country",
    "dim_currency",
)


def _build_serving(path, *, reversed_rows: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))

    con.execute(
        "create table agg_transactions_daily ("
        "event_date_utc date, debtor_country varchar, status varchar, "
        "transaction_count integer, amount_eur_total decimal(38,2))"
    )
    transactions_rows = [
        "(date '2026-01-01', 'FR', 'ACCEPTED', 10, 100.50)",
        "(date '2026-01-02', 'DE', 'REJECTED', 5, 200.00)",
        "(date '2026-01-01', 'FR', 'ACCEPTED', 10, NULL)",
    ]
    if reversed_rows:
        transactions_rows = list(reversed(transactions_rows))
    con.execute("insert into agg_transactions_daily values " + ", ".join(transactions_rows))

    con.execute(
        "create table agg_transactions_channel_daily ("
        "event_date_utc date, channel varchar, status varchar, transaction_count integer)"
    )
    con.execute(
        "insert into agg_transactions_channel_daily values "
        "(date '2026-01-01', 'ONLINE', 'ACCEPTED', 10), "
        "(date '2026-01-02', 'POS', 'REJECTED', 5)"
    )

    con.execute(
        "create table agg_fx_exposure_daily ("
        "event_date_utc date, currency_code varchar, "
        "is_carried_forward boolean, fx_rate_used double)"
    )
    fx_rows = [
        "(date '2026-01-01', 'EUR', false, 1.0)",
        "(date '2026-01-02', 'USD', true, NULL)",
    ]
    if reversed_rows:
        fx_rows = list(reversed(fx_rows))
    con.execute("insert into agg_fx_exposure_daily values " + ", ".join(fx_rows))

    con.execute("create table data_quality_daily (ingestion_date date, received_row_count integer)")
    con.execute("insert into data_quality_daily values (date '2026-01-01', 15)")

    con.execute("create table dim_country (alpha_2 varchar, country_name varchar)")
    con.execute("insert into dim_country values ('FR', 'France'), ('DE', 'Germany')")

    con.execute("create table dim_currency (currency_code varchar, minor_units integer)")
    con.execute("insert into dim_currency values ('EUR', 2), ('USD', 2)")

    con.close()


def _rebuild_table(source_con, rebuilt_con, snapshot_dir, table: str, csv_file: str) -> None:
    columns = source_con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_name = ? order by ordinal_position",
        [table],
    ).fetchall()
    ddl = ", ".join(f'"{name}" {data_type}' for name, data_type in columns)
    rebuilt_con.execute(f'create table "{table}" ({ddl})')
    csv_path = snapshot_dir / csv_file
    rebuilt_con.execute(f"copy \"{table}\" from '{csv_path}' (header, delimiter ',')")
    return columns


def test_reconstructing_from_csv_matches_the_source_exactly(tmp_path) -> None:
    serving_path = tmp_path / "serving" / "marts.duckdb"
    _build_serving(serving_path)
    snapshot_dir = tmp_path / "snapshot"

    export_snapshot(serving_path, snapshot_dir)

    source_con = duckdb.connect(str(serving_path), read_only=True)
    rebuilt_con = duckdb.connect(str(tmp_path / "rebuilt.duckdb"))
    try:
        for table in SNAPSHOT_TABLES:
            source_columns = source_con.execute(
                "select column_name, data_type from information_schema.columns "
                "where table_name = ? order by ordinal_position",
                [table],
            ).fetchall()
            rebuilt_columns = _rebuild_table(
                source_con, rebuilt_con, snapshot_dir, table, f"{table}.csv"
            )
            assert rebuilt_columns == source_columns

            source_rows = source_con.execute(f'select count(*) from "{table}"').fetchone()[0]
            rebuilt_rows = rebuilt_con.execute(f'select count(*) from "{table}"').fetchone()[0]
            assert rebuilt_rows == source_rows

            source_fingerprint = table_fingerprint(source_con, table)
            rebuilt_fingerprint = table_fingerprint(rebuilt_con, table)
            assert rebuilt_fingerprint == source_fingerprint
    finally:
        source_con.close()
        rebuilt_con.close()


def test_two_exports_produce_byte_identical_csv_regardless_of_storage_order(tmp_path) -> None:
    serving_path = tmp_path / "serving" / "marts.duckdb"
    _build_serving(serving_path, reversed_rows=False)
    first_dir = tmp_path / "first"
    export_snapshot(serving_path, first_dir)

    reordered_path = tmp_path / "serving-reordered" / "marts.duckdb"
    _build_serving(reordered_path, reversed_rows=True)
    second_dir = tmp_path / "second"
    export_snapshot(reordered_path, second_dir)

    for table in SNAPSHOT_TABLES:
        first_bytes = (first_dir / f"{table}.csv").read_bytes()
        second_bytes = (second_dir / f"{table}.csv").read_bytes()
        assert first_bytes == second_bytes

    repeat_dir = tmp_path / "repeat"
    export_snapshot(serving_path, repeat_dir)
    for table in SNAPSHOT_TABLES:
        assert (first_dir / f"{table}.csv").read_bytes() == (
            repeat_dir / f"{table}.csv"
        ).read_bytes()


def test_manifest_rows_and_fingerprints_match_the_rebuilt_tables(tmp_path) -> None:
    serving_path = tmp_path / "serving" / "marts.duckdb"
    _build_serving(serving_path)
    snapshot_dir = tmp_path / "snapshot"

    export_snapshot(serving_path, snapshot_dir)

    manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    manifest_by_name = {entry["name"]: entry for entry in manifest["tables"]}
    assert set(manifest_by_name) == set(SNAPSHOT_TABLES)

    source_con = duckdb.connect(str(serving_path), read_only=True)
    rebuilt_con = duckdb.connect(str(tmp_path / "rebuilt.duckdb"))
    try:
        for table in SNAPSHOT_TABLES:
            entry = manifest_by_name[table]
            _rebuild_table(source_con, rebuilt_con, snapshot_dir, table, entry["csv_file"])

            rebuilt_rows = rebuilt_con.execute(f'select count(*) from "{table}"').fetchone()[0]
            rebuilt_fingerprint = table_fingerprint(rebuilt_con, table)

            assert entry["rows"] == rebuilt_rows
            assert entry["fingerprint"] == rebuilt_fingerprint
    finally:
        source_con.close()
        rebuilt_con.close()
