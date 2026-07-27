"""DuckDB round-trip of a landed partition: schema, typing, and null handling."""

from datetime import UTC, date

import duckdb
import pyarrow.parquet as pq
import pytest

from payments.generator.generate import generate_batch
from payments.generator.schema import RAW_COLUMNS
from payments.ingestion.land import land_batch, partition_path

RUN_DATE = date(2026, 7, 21)

EXPECTED_FILE_COLUMNS = tuple(column for column in RAW_COLUMNS if column != "ingestion_date")


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PAYMENTS_DATA_DIR", str(tmp_path))
    return tmp_path / "raw" / "transactions"


def _glob(raw_dir):
    return str(raw_dir / "ingestion_date=*" / "*.parquet")


def test_hive_read_reconstitutes_fourteen_columns_and_ingestion_date(raw_dir):
    rows = generate_batch(RUN_DATE, n_rows=200, seed=1)
    land_batch(rows, RUN_DATE)

    con = duckdb.connect()
    columns = con.execute(
        f"describe select * from read_parquet('{_glob(raw_dir)}', hive_partitioning = 1)"
    ).fetchall()
    assert len(columns) == 14

    distinct_dates = con.execute(
        f"select distinct ingestion_date from read_parquet('{_glob(raw_dir)}', "
        "hive_partitioning = 1)"
    ).fetchall()
    assert distinct_dates == [(RUN_DATE,)]


def test_file_column_order_matches_raw_columns_without_ingestion_date(raw_dir):
    # Checked against the file's own schema via pyarrow, not through DuckDB's
    # read_parquet: DuckDB auto-detects Hive-style partitioning from the
    # `ingestion_date=...` directory name even without hive_partitioning=1,
    # and would silently append a reconstituted ingestion_date column to the
    # result, hiding what the file itself actually contains.
    rows = generate_batch(RUN_DATE, n_rows=50, seed=1)
    land_batch(rows, RUN_DATE)

    partition = partition_path(RUN_DATE)
    file_path = partition / "part-0000.parquet"

    schema = pq.read_schema(file_path)
    assert tuple(schema.names) == EXPECTED_FILE_COLUMNS


def test_all_string_columns_are_varchar_including_when_all_null(raw_dir):
    rows = generate_batch(RUN_DATE, n_rows=20, seed=1)
    for row in rows:
        row["rejection_reason"] = None

    land_batch(rows, RUN_DATE)

    con = duckdb.connect()
    columns = con.execute(
        f"describe select * from read_parquet('{_glob(raw_dir)}', hive_partitioning = 1)"
    ).fetchall()
    types_by_name = {row[0]: row[1] for row in columns}
    string_columns = tuple(column for column in RAW_COLUMNS if column != "ingestion_date")
    for column in string_columns:
        if column == "ingested_at":
            continue
        assert types_by_name[column] == "VARCHAR", f"{column} is {types_by_name[column]}"
    assert types_by_name["rejection_reason"] == "VARCHAR"


def test_null_and_empty_string_do_not_get_confused(raw_dir):
    base = generate_batch(RUN_DATE, n_rows=1, seed=1)[0]

    null_row = base.copy()
    null_row["transaction_id"] = "TXN-NULL-CASE"
    null_row["currency"] = None

    empty_row = base.copy()
    empty_row["transaction_id"] = "TXN-EMPTY-CASE"
    empty_row["currency"] = ""

    land_batch([null_row, empty_row], RUN_DATE)

    con = duckdb.connect()
    result = dict(
        con.execute(
            f"select transaction_id, currency from read_parquet('{_glob(raw_dir)}', "
            "hive_partitioning = 1)"
        ).fetchall()
    )
    assert result["TXN-NULL-CASE"] is None
    assert result["TXN-EMPTY-CASE"] == ""


def test_null_transaction_id_reads_back_as_null(raw_dir):
    base = generate_batch(RUN_DATE, n_rows=1, seed=1)[0]
    row = base.copy()
    row["transaction_id"] = None

    land_batch([row], RUN_DATE)

    con = duckdb.connect()
    result = con.execute(
        f"select transaction_id from read_parquet('{_glob(raw_dir)}', hive_partitioning = 1)"
    ).fetchall()
    assert result == [(None,)]


def test_ingested_at_round_trips_as_timezone_aware_timestamp(raw_dir):
    rows = generate_batch(RUN_DATE, n_rows=5, seed=1)
    land_batch(rows, RUN_DATE)

    con = duckdb.connect()
    result = con.execute(
        f"select ingested_at from read_parquet('{_glob(raw_dir)}', hive_partitioning = 1) limit 1"
    ).fetchone()
    read_back = result[0]
    assert read_back.tzinfo is not None
    assert read_back.astimezone(UTC) == rows[0]["ingested_at"].astimezone(UTC)


def test_three_dates_give_three_partitions_and_global_read_sums_rows(raw_dir):
    dates = [date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)]
    counts = [50, 75, 30]
    for run_date, n_rows in zip(dates, counts, strict=True):
        land_batch(generate_batch(run_date, n_rows=n_rows, seed=1), run_date)

    partition_dirs = sorted(p.name for p in raw_dir.iterdir())
    assert partition_dirs == [f"ingestion_date={d.isoformat()}" for d in sorted(dates)]

    con = duckdb.connect()
    total = con.execute(
        f"select count(*) from read_parquet('{_glob(raw_dir)}', hive_partitioning = 1)"
    ).fetchone()[0]
    assert total == sum(counts)
