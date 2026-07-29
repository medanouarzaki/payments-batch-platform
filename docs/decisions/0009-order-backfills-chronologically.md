# 0009. Order backfills chronologically

## Context

`int_transactions_deduped` and every mart built on it compute their
incremental window from `max(ingestion_date)` over all of staging, not from
the day a given run processes. A backfill landing its oldest day last
rather than first changes what that maximum is when each day's dbt build
runs, and therefore where the window starts. This was measured directly:
processing eleven consecutive days chronologically covers all eleven dates
in `data_quality_daily`; the same eleven days newest-first cover only
seven, the four oldest having landed outside the window on their first
attempt and never having been reintegrated. Within the window itself order
does not matter — a five-day scenario produces byte-identical marts either
way — but past it, order changes which data ends up in the warehouse at
all, silently and without any dbt error.

## Decision

The DAG sets `depends_on_past=True` on the three dbt tasks and
`max_active_runs=1`, so a backfill can only proceed in strict chronological
order: a day's dbt build does not start until the previous day's has
succeeded. This is a correctness requirement, not an operational
convenience, because the measurement above shows out-of-order processing
beyond the dedup window silently drops data rather than merely reordering
its arrival.

## Alternatives I considered

Passing the partition date being processed into the dbt models, so the
window could be computed relative to that date instead of the global
maximum, would remove the ordering requirement and let days run in any
order or in parallel. Rejected for this block: it changes the contract of
every incremental model reading `max(ingestion_date)`, a larger change than
this backfill needed, and the ordering already available through
`depends_on_past` suffices to make any backfill correct today without
touching a single model.

## Consequences

A single failed day blocks every later day in the same backfill until
fixed, since nothing downstream of a failure may start out of order. A
thirty-day backfill failing on day three cannot progress further until day
three is resolved, even though later days have no data dependency on it
beyond the scheduler's ordering rule. I accept this because the
alternative — letting later days run ahead of a failed earlier one — is
exactly the ordering this block measured to silently lose data once the
gap exceeds the dedup window.

## Date

2026-07-29
