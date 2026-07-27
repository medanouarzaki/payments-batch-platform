import os
import subprocess
import sys
from datetime import date, timedelta

from payments.generator import batch_fingerprint, derive_seed, generate_batch


def test_same_date_and_seed_gives_same_fingerprint():
    run_date = date(2026, 7, 20)
    fp1 = batch_fingerprint(generate_batch(run_date, n_rows=200, seed=123))
    fp2 = batch_fingerprint(generate_batch(run_date, n_rows=200, seed=123))
    assert fp1 == fp2


def test_different_dates_give_different_fingerprints():
    fp1 = batch_fingerprint(generate_batch(date(2026, 7, 20), n_rows=200, seed=123))
    fp2 = batch_fingerprint(generate_batch(date(2026, 7, 21), n_rows=200, seed=123))
    assert fp1 != fp2


def test_different_seeds_same_date_give_different_fingerprints():
    run_date = date(2026, 7, 20)
    fp1 = batch_fingerprint(generate_batch(run_date, n_rows=200, seed=123))
    fp2 = batch_fingerprint(generate_batch(run_date, n_rows=200, seed=456))
    assert fp1 != fp2


def test_fingerprint_is_stable_across_processes_with_different_hash_seeds():
    script = (
        "from datetime import date;"
        "from payments.generator import batch_fingerprint, generate_batch;"
        "print(batch_fingerprint(generate_batch(date(2026, 7, 20), n_rows=200, seed=123)))"
    )

    result_0 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        check=True,
    )
    result_1 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "1"},
        check=True,
    )

    assert result_0.stdout.strip() == result_1.stdout.strip()
    assert result_0.stdout.strip() != ""


def test_derive_seed_is_deterministic_and_varies_by_date():
    run_date = date(2026, 7, 20)
    next_date = run_date + timedelta(days=1)
    assert derive_seed(123, run_date) == derive_seed(123, run_date)
    assert derive_seed(123, run_date) != derive_seed(123, next_date)
