"""Integration coverage of the serving publication: concurrency, failure, replay."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

import payments.publish.export_marts as export_marts_module
from payments.publish.export_marts import SERVING_TABLES, export_marts
from payments.publish.fingerprint import table_fingerprint

HOLDER = str(Path(__file__).parent / "_serving_holder.py")


def _build_source(path: Path) -> None:
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


def _start_holder(path: Path, mode: str, table: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, HOLDER, str(path), mode, table],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    first = proc.stdout.readline().strip()
    if first != "READY":
        rest = proc.stdout.read()
        proc.wait(timeout=10)
        raise RuntimeError(f"holder failed to start: {first}\n{rest}")
    return proc


def _ask(proc: subprocess.Popen, command: str) -> str:
    proc.stdin.write(command + "\n")
    proc.stdin.flush()
    return proc.stdout.readline().strip()


def _stop_holder(proc: subprocess.Popen) -> None:
    try:
        proc.stdin.write("X\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=10)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_publication_succeeds_while_a_reader_holds_the_warehouse(tmp_path) -> None:
    source = tmp_path / "source.duckdb"
    _build_source(source)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    holder = _start_holder(source, "ro", "agg_transactions_daily")
    try:
        result = export_marts(source, serving_path)
    finally:
        _stop_holder(holder)

    assert result.row_counts == {table: 2 for table in SERVING_TABLES}
    tmp_file = serving_path.parent / (serving_path.name + ".tmp")
    assert not tmp_file.exists()


def test_a_failure_midway_leaves_no_temporary_and_keeps_the_previous_file(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.duckdb"
    _build_source(source)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    export_marts(source, serving_path)
    previous_bytes = serving_path.read_bytes()

    original_copy = export_marts_module._copy_table

    def _failing_copy(con, table):
        if table == SERVING_TABLES[1]:
            raise RuntimeError("simulated failure")
        return original_copy(con, table)

    monkeypatch.setattr(export_marts_module, "_copy_table", _failing_copy)

    with pytest.raises(RuntimeError):
        export_marts(source, serving_path)

    tmp_file = serving_path.parent / (serving_path.name + ".tmp")
    assert not tmp_file.exists()
    assert serving_path.read_bytes() == previous_bytes


def test_replaying_a_publication_yields_the_same_content_and_bytes(tmp_path) -> None:
    source = tmp_path / "source.duckdb"
    _build_source(source)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    export_marts(source, serving_path)
    first_con = duckdb.connect(str(serving_path), read_only=True)
    first_fingerprints = {table: table_fingerprint(first_con, table) for table in SERVING_TABLES}
    first_con.close()
    first_sha = _sha256(serving_path)

    export_marts(source, serving_path)
    second_con = duckdb.connect(str(serving_path), read_only=True)
    second_fingerprints = {table: table_fingerprint(second_con, table) for table in SERVING_TABLES}
    second_con.close()
    second_sha = _sha256(serving_path)

    for table in SERVING_TABLES:
        assert first_fingerprints[table] == second_fingerprints[table], (
            f"fingerprint of {table} differs between passes"
        )
    assert first_sha == second_sha, "serving file bytes differ between two publications"


def test_a_reader_opened_before_a_replacement_keeps_answering(tmp_path) -> None:
    source = tmp_path / "source.duckdb"
    _build_source(source)
    serving_path = tmp_path / "serving" / "marts.duckdb"

    export_marts(source, serving_path)

    holder = _start_holder(serving_path, "ro", "agg_transactions_daily")
    try:
        before = _ask(holder, "Q")
        assert before == "QUERY_OK count=2"
        inode_before = serving_path.stat().st_ino

        writer = duckdb.connect(str(source))
        writer.execute(
            "insert into agg_transactions_daily values (date '2026-01-03', 'IT', 'ACCEPTED', 7)"
        )
        writer.close()

        export_marts(source, serving_path)
        inode_after = serving_path.stat().st_ino
        assert inode_after != inode_before

        after = _ask(holder, "Q")
        assert after == "QUERY_OK count=2"
    finally:
        _stop_holder(holder)

    new_con = duckdb.connect(str(serving_path), read_only=True)
    new_count = new_con.execute("select count(*) from agg_transactions_daily").fetchone()[0]
    new_con.close()
    assert new_count == 3
