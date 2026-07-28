# 0011. Assume naive timestamps are UTC

## Context

`stg_transactions` has to turn three shapes of `event_timestamp` into one UTC instant:
a `Z`-suffixed value, a value with an explicit numeric offset, and a naive value with
neither. The first two carry enough information to compute a correct instant with a
direct cast. The naive form does not: nothing in the row says which time zone the
sender meant. On the ten partitions I built this model against, 25,523 of 319,171 rows
(7.997%) land in this naive bucket, tagged `TS_ASSUMED_UTC`, close to the 8% the
synthetic generator's catalog advertises for this defect. I measured this on data
produced by a generator that always emits UTC to begin with, then strips the offset to
simulate the defect, so in this dataset the assumption happens to be exactly right; a
real upstream system would not offer that guarantee.

## Decision

I will interpret every naive `event_timestamp` as already being UTC, converting it with
an explicit `at time zone 'UTC'` rather than a bare cast that would silently depend on
the session's time zone setting. I flag every row this applies to with
`TS_ASSUMED_UTC` so the assumption is visible downstream rather than invisible.

## Alternatives I considered

I considered quarantining naive timestamps instead of assuming a time zone for them,
treating "no time zone stated" as inherently unreliable data. I rejected this because it
would quarantine 8% of every batch by construction, which is disproportionate to a
defect that, on this generator's data, is always factually correct once resolved.

## Consequences

If a real source ever emits naive timestamps in a time zone other than UTC, this model
will silently compute the wrong instant for those rows: nothing in the pipeline would
detect or flag that specific failure mode, since `TS_ASSUMED_UTC` only marks that the
assumption was applied, not whether it was correct. I accept this because reversing the
decision would mean quarantining a large, currently-harmless share of every batch on the
mere absence of a time zone marker.

## Date

2026-07-28
