# 0022. Verify each published guarantee by mutation

## Context

`docs/quality.md` listed eight properties under a sentence claiming each was enforced by
tests running on every pull request, and that each had been seen fail on a defect
introduced on purpose. That was true of each test the day it was written. Nothing kept it
true afterwards.

One mutation per property, exercised in the mode where the defect shows: nine mutations
run, one discarded as invalid because it broke an unrelated assertion before the property
under test was ever reached. Six properties held. Two did not.

Dropping roughly one valid row in ten from `int_transactions_deduped` passed all 78 dbt
tests. `data_quality_daily` computes `duplicate_removed_count` as `valid_row_count` minus
`deduplicated_row_count`, so rows lost from the fact table reappear in that subtraction as
duplicates that were never there, and the published accounting still balances. The test
that was supposed to catch this, `reconciliation_by_ingestion_date`, reduced algebraically
to a constant zero.

Replacing the quarantine-rate comparison in `airflow/scripts/dq_gate.py` with `if False`
passed all 187 python tests, at 95.40% coverage of `src/payments/`. The script sits outside
that package and nothing exercised it.

## Decision

`reconciliation_by_ingestion_date.sql` is deleted. `assert_data_quality_daily_accounting`
is rewritten to measure duplicates independently on `stg_transactions` rather than restate
a subtraction. `assert_valid_rows_reach_the_fact_table` is added: every valid transaction
id inside the deduplication window must appear in the fact table. `tests/unit/test_dq_gate.py`
covers the gate's four exit paths through a subprocess against a temporary warehouse.

Each new test was then run against the mutation it claims to catch, and seen fail.

## Alternatives I considered

Softening the wording of `docs/quality.md` and leaving the tests alone. Rejected: the value
of that sentence is that it can be checked, and two of the eight claims were simply false.

Writing the conservation check globally rather than scoped to the deduplication window. Its
first version was global, and it immediately failed two existing tests that deliberately
exercise partitions dropped for being older than the window. The two statements were
incompatible. Scoping the new test and writing the limitation into its header was the
honest resolution; changing the backfill tests would have hidden a real behaviour.

## Consequences

191 python tests and 78 dbt tests, all green. The window limitation is now written where
the test lives rather than only in a design document.

The mutation results are a snapshot. Nothing re-runs them, so this sentence can rot exactly
as the previous one did. What this record buys is that the exact edit behind each mutation
is written down, so checking again is a copy and a paste rather than an investigation.

## Date

2026-08-02
