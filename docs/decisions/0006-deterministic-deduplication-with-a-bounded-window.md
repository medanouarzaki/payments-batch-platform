# 0006. Deterministic deduplication with a bounded window

## Context

`int_transactions_deduped` needs to keep exactly one row per `transaction_id` among
2,501 eliminated duplicates out of 316,265 valid staging rows across the ten partitions
this pipeline builds from, using an order that never leaves a winner ambiguous:
`event_timestamp_utc desc`, then `ingested_at desc`, then `row_hash asc` as a tie-break.
On this dataset, the tie-break never actually arbitrates between two distinct
candidates: all 1,559 groups tied on the first two criteria consist of rows sharing the
same `row_hash` (exact duplicates), so its necessity is proven only on hand-built data,
not exercised by what the generator currently produces. Separately, re-scanning all ten
days on every run would grow linearly with history for no benefit, since every measured
collision spans zero days between its first and last `ingestion_date`.

## Decision

I will run the model incrementally, `delete+insert` keyed on `transaction_id`, rescanning
only the last `dedup_window_days` (7 by default) days of staging on each incremental
run, while the first build reads all valid history to establish a correct initial state.

## Alternatives I considered

I considered recomputing the full history on every run instead of windowing it, which
guarantees no duplicate is ever missed regardless of how late it arrives. I rejected
this because it makes every run's cost grow with the lifetime of the pipeline instead of
with a single day's volume, for a scenario that, on the measured collision spread
(always zero days), buys correctness this dataset does not need.

## Consequences

A duplicate whose second occurrence lands more than 7 days after the first will not be
detected: the model has already moved its window past the earlier occurrence and will
not revisit it. The operational answer is the vigilance test added alongside this
model, which flags exactly this situation when it happens; today it passes vacuously,
since it has never been exercised by real data, only by a hand-built case reproducing a
collision that spans the window boundary. I accept this because the alternative is an
unbounded, ever-growing recomputation cost paid up front for a failure mode that has
not yet occurred once in this pipeline's actual data.

## Date

2026-07-28
