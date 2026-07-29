"""Behavior of export_marts: atomic publication, failure cleanup, idempotence."""

from __future__ import annotations

import duckdb
import pytest

import payments.publish.export_marts as export_marts_module
from payments.publish.export_marts import export_marts
from payments.publish.fingerprint import table_fingerprint

EXPECTED_SERVING_TABLES: tuple[str, ...] = (
    "agg_transactions_daily",
    "agg_transactions_channel_daily",
    "agg_fx_exposure_daily",
    "data_quality_daily",
    "dim_country",
    "dim_currency",
)


def _build_warehouse(path) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        "create table agg_transactions_daily "
        "(event_date_utc date, debtor_country varchar, "
        "status varchar, transaction_count integer)"
    )
    con.execute(
        "insert into agg_transactions_daily values "
        "(date '2026-01-01', 'FR', 'ACCEPTED', 10), "
        "(date '2026-01-02', 'DE', 'REJECTED', 5)"
    )
    con.execute(
        "create table agg_transactions_channel_daily "
        "(event_date_utc date, channel varchar, "
        "status varchar, transaction_count integer)"
    )
    con.execute(
        "insert into agg_transactions_channel_daily values "
        "(date '2026-01-01', 'ONLINE', 'ACCEPTED', 10), "
        "(date '2026-01-02', 'POS', 'REJECTED', 5)"
    )
    con.execute(
        "create table agg_fx_exposure_daily "
        "(event_date_utc date, currency_code varchar, transaction_count integer)"
    )
    con.execute(
        "insert into agg_fx_exposure_daily values "
        "(date '2026-01-01', 'EUR', 10), "
        "(date '2026-01-02', 'USD', 5)"
    )
    con.execute(
        "create table data_quality_daily "
        "(ingestion_date date, received_row_count integer, checked_at timestamptz)"
    )
    con.execute(
        "insert into data_quality_daily values "
        "(date '2026-01-01', 15, timestamptz '2026-01-01 10:00:00+00'), "
        "(date '2026-01-02', 20, timestamptz '2026-01-02 11:00:00+00')"
    )
    con.execute("create table dim_country (alpha_2 varchar, name varchar)")
    con.execute("insert into dim_country values ('FR', 'France'), ('DE', 'Germany')")
    con.execute("create table dim_currency (currency_code varchar, minor_units integer)")
    con.execute("insert into dim_currency values ('EUR', 2), ('USD', 2)")
    con.close()


def test_export_writes_every_serving_table_with_its_row_count(tmp_path) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(warehouse_path)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    result = export_marts(warehouse_path, serving_path)

    assert set(result.row_counts.keys()) == set(EXPECTED_SERVING_TABLES)
    assert result.row_counts == {table: 2 for table in EXPECTED_SERVING_TABLES}

    con = duckdb.connect(str(serving_path), read_only=True)
    for table in EXPECTED_SERVING_TABLES:
        assert con.execute(f"select count(*) from {table}").fetchone()[0] == 2
    con.close()


def test_export_leaves_no_temporary_file_behind(tmp_path) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(warehouse_path)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    export_marts(warehouse_path, serving_path)

    tmp_file = serving_path.parent / (serving_path.name + ".tmp")
    assert not tmp_file.exists()


def test_export_removes_the_temporary_file_after_a_failure(tmp_path, monkeypatch) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(warehouse_path)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    original_copy = export_marts_module._copy_table

    def _failing_copy(con, table):
        if table == EXPECTED_SERVING_TABLES[1]:
            raise RuntimeError("simulated failure")
        return original_copy(con, table)

    monkeypatch.setattr(export_marts_module, "_copy_table", _failing_copy)

    with pytest.raises(RuntimeError):
        export_marts(warehouse_path, serving_path)

    tmp_file = serving_path.parent / (serving_path.name + ".tmp")
    assert not tmp_file.exists()


def test_export_keeps_the_previous_serving_file_after_a_failure(tmp_path, monkeypatch) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(warehouse_path)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    export_marts(warehouse_path, serving_path)
    previous_bytes = serving_path.read_bytes()

    original_copy = export_marts_module._copy_table

    def _failing_copy(con, table):
        if table == EXPECTED_SERVING_TABLES[1]:
            raise RuntimeError("simulated failure")
        return original_copy(con, table)

    monkeypatch.setattr(export_marts_module, "_copy_table", _failing_copy)

    with pytest.raises(RuntimeError):
        export_marts(warehouse_path, serving_path)

    assert serving_path.read_bytes() == previous_bytes


def test_export_replaces_an_existing_serving_file(tmp_path) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(warehouse_path)
    serving_path = tmp_path / "serving" / "marts.duckdb"
    serving_path.parent.mkdir(parents=True)
    serving_path.write_bytes(b"not a duckdb file")

    export_marts(warehouse_path, serving_path)

    con = duckdb.connect(str(serving_path), read_only=True)
    assert con.execute("select count(*) from dim_country").fetchone()[0] == 2
    con.close()


def test_export_does_not_modify_the_source_warehouse(tmp_path) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(warehouse_path)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    before = warehouse_path.stat()
    export_marts(warehouse_path, serving_path)
    after = warehouse_path.stat()

    assert after.st_size == before.st_size
    assert after.st_mtime == before.st_mtime


def test_export_is_idempotent_by_content_fingerprint(tmp_path) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(warehouse_path)
    first_path = tmp_path / "serving" / "first.duckdb"
    second_path = tmp_path / "serving" / "second.duckdb"

    export_marts(warehouse_path, first_path)
    export_marts(warehouse_path, second_path)

    first_con = duckdb.connect(str(first_path), read_only=True)
    second_con = duckdb.connect(str(second_path), read_only=True)
    for table in EXPECTED_SERVING_TABLES:
        assert table_fingerprint(first_con, table) == table_fingerprint(second_con, table)
    first_con.close()
    second_con.close()


def test_serving_file_contains_exactly_the_declared_tables(tmp_path) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(warehouse_path)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    export_marts(warehouse_path, serving_path)

    con = duckdb.connect(str(serving_path), read_only=True)
    tables = {
        row[0]
        for row in con.execute(
            "select table_name from information_schema.tables where table_schema = 'main'"
        ).fetchall()
    }
    con.close()

    assert tables == set(EXPECTED_SERVING_TABLES)
