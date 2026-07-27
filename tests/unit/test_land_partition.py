"""Partition-level behavior of land_batch: single file, atomic replace, path guard."""

import hashlib
from datetime import date

import pyarrow.parquet as pq
import pytest

from payments.generator.generate import generate_batch
from payments.ingestion.land import LandingError, land_batch, partition_path

RUN_DATE = date(2026, 7, 21)


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PAYMENTS_DATA_DIR", str(tmp_path))
    return tmp_path / "raw" / "transactions"


def _rows(n, seed=1, run_date=RUN_DATE):
    return generate_batch(run_date, n_rows=n, seed=seed)


def test_fresh_partition_has_single_file(raw_dir):
    rows = _rows(500)
    result = land_batch(rows, RUN_DATE)

    partition = partition_path(RUN_DATE)
    files = list(partition.iterdir())
    assert [f.name for f in files] == ["part-0000.parquet"]
    assert result.path == partition / "part-0000.parquet"
    assert result.rows == len(rows)


def test_rewrite_replaces_partition_without_residue(raw_dir):
    land_batch(_rows(500, seed=1), RUN_DATE)

    # A stray leftover file with a name land_batch never writes itself (unlike
    # part-0000.parquet, which every write targets and os.replace would
    # overwrite regardless of whether old content is ever cleared). Only a
    # genuine "replace the whole partition" step removes this.
    partition = partition_path(RUN_DATE)
    stray_file = partition / "part-0001.parquet"
    stray_file.write_bytes(b"leftover from a previous run")

    result = land_batch(_rows(300, seed=2), RUN_DATE)

    files = list(partition.iterdir())
    assert [f.name for f in files] == ["part-0000.parquet"]

    table = pq.read_table(result.path)
    assert table.num_rows == 300


def test_fingerprint_is_deterministic(raw_dir):
    rows = _rows(500)
    result_1 = land_batch(rows, RUN_DATE)
    result_2 = land_batch(rows, RUN_DATE)
    assert result_1.sha256 == result_2.sha256
    assert result_1.bytes_written == result_2.bytes_written


def test_failed_write_leaves_no_tmp_and_preserves_previous_file(raw_dir, monkeypatch):
    good_result = land_batch(_rows(500, seed=1), RUN_DATE)

    def _boom(table, where, **kwargs):
        with open(where, "wb") as handle:
            handle.write(b"partial")
        raise RuntimeError("boom")

    monkeypatch.setattr("payments.ingestion.land.pq.write_table", _boom)

    with pytest.raises(RuntimeError):
        land_batch(_rows(300, seed=2), RUN_DATE)

    partition = partition_path(RUN_DATE)
    files = sorted(f.name for f in partition.iterdir()) if partition.exists() else []
    assert ".tmp" not in "".join(files)

    final_file = partition / "part-0000.parquet"
    assert final_file.exists(), (
        "part-0000.parquet from the previous successful write did not survive the "
        "failed rewrite attempt"
    )
    final_bytes = final_file.read_bytes()
    assert hashlib.sha256(final_bytes).hexdigest() == good_result.sha256
    table = pq.read_table(final_file)
    assert table.num_rows == good_result.rows


def test_path_guard_rejects_base_dir_outside_raw_transactions_dir(tmp_path):
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    sentinel = outside_dir / "sentinel.txt"
    sentinel.write_text("do not touch")

    with pytest.raises(LandingError):
        land_batch(_rows(10), RUN_DATE, base_dir=outside_dir)

    assert sentinel.exists()
    assert sentinel.read_text() == "do not touch"


def test_mismatched_ingestion_date_raises_and_writes_nothing(raw_dir):
    rows = _rows(10)
    rows[3]["ingestion_date"] = date(2026, 1, 1)

    with pytest.raises(LandingError):
        land_batch(rows, RUN_DATE)

    partition = partition_path(RUN_DATE)
    assert not partition.exists()
