# 0007. Use delete+insert as the incremental strategy for marts

## Context

Every incremental model in the marts layer — `fct_transactions` and the three
aggregates built on top of it — needs to rebuild only the rows a run affects,
without leaving stale or duplicated rows behind. The aggregates complicate
this: a group's membership can change between runs, for example when a
country resolves differently or a fx status flips from carried forward to
ok, so a naive row-level upsert on the aggregate's own key cannot guarantee
correctness.

## Decision

Every incremental model here is configured with
`incremental_strategy='delete+insert'` and a unique key matching its grain.
For the aggregates, the key is the coarse dimension of the grain — a single
date, not the full grouping key — so a whole group is deleted and reinserted
as one unit rather than merged row by row. The incremental filter is split
into two uses: it identifies which coarse keys a run touched, but never
restricts which rows get aggregated once a key is selected. Each touched
date is recomputed from that date's complete history upstream, not from the
slice of rows the current run added, which is what lets a late-arriving row
correct a total already published days earlier.

## Alternatives I considered

A `merge` strategy keyed on the full grouping key would avoid deleting
anything, but it cannot make a group disappear: if a country or status
combination from a previous run no longer has any rows, merge leaves its
stale row untouched. Rejected because a mart that never drops rows
misrepresents reality once reality stops matching history. I also
considered filtering the aggregation itself to the incremental window,
cheaper but wrong: it recomputes a date's total from only its newest rows
and silently discards every row an earlier run contributed — exactly the
failure this project measured before writing any aggregate.

## Consequences

Every touched date is rewritten from its full history on every run, even
when only one row in it changed, costing more compute than a row-level
merge. The incremental window is also wider than the current dataset can be
shown to require: no scenario built from this project's data exercises the
boundary case it exists for, a deduplication winner changing on a date no
current-run row touches, so its necessity rests on reasoning about the
dedup window rather than an observed failure.

## Date

2026-07-28
