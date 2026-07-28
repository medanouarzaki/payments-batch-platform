# 0005. Quarantine invalid rows instead of dropping them

## Context

`stg_transactions` already computes `is_valid` from `dq_flags` for every row, using the
same blocking-reason macro that will later apply to `int_transactions_deduped`. On the
ten partitions this pipeline builds from, 2,906 of 319,171 rows are invalid: 1,221 for
`MISSING_CURRENCY`, 917 for `NON_POSITIVE_AMOUNT`, 623 for `UNKNOWN_CURRENCY`, and 152
for `MISSING_KEY`, with seven rows carrying two of these reasons at once. I need a model
downstream of staging that does something with these rows rather than letting them
silently vanish from every report built on top of valid transactions.

## Decision

I will materialize `quarantine_transactions`, an incremental model reading only from
`stg_transactions` and keeping the rows where `is_valid` is false, each carrying the
subset of `dq_flags` that are blocking reasons under the column `quarantine_reasons`. A
singular test asserts that quarantine and staging agree exactly, per `ingestion_date`
and by `row_hash`, so the two can never silently drift apart.

## Alternatives I considered

I considered filtering invalid rows out of staging and downstream models without
recording them anywhere, on the reasoning that a report built only from clean data is
simpler to reason about. I rejected this because it destroys the only trace that 0.91%
of a batch failed validation, which is exactly the number an operator or a later
reconciliation would need to explain a volume drop.

## Consequences

Every batch now produces two outputs to reconcile instead of one, and any model built
on top of `stg_transactions` has to decide explicitly whether to read from it directly
or to exclude what `quarantine_transactions` already holds; forgetting that split will
silently double-count or drop rows. I accept this added bookkeeping because losing the
2,906 quarantined rows without a record would be worse: nobody downstream would be able
to tell a clean batch from one that silently dropped nearly 1% of its transactions.

## Date

2026-07-28
