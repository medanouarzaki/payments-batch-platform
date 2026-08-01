# 0019. Rebuild the warehouse after a retroactive rate correction

## Context

Seven content fingerprints had stood as the project's reference since the marts were
built, and had not been reverified since the models were last edited. Rebuilding the
whole warehouse from unchanged inputs showed four of the seven differ.

The difference is confined. On 3,526,366 rows matched by transaction id, no row differs
on any column outside currency conversion, and 63,348 rows differ on all five conversion
columns at once. Every one of them moved from `unavailable` to `ok` or `carried_forward`;
no row moved the other way. The cause is dated: the rate cache entries those rows depend
on were written 111 to 119 days after the transactions were ingested, in four calls made
within one minute of each other, when a gap in the cache was filled. The fact table only
reconsiders rows whose ingestion date falls inside the deduplication window, so days
already outside it kept a conversion status the cache no longer justifies.

Rebuilding with the models as they stood before they were last edited produced the same
fingerprints as the current models, which clears the SQL of any part in the difference.

## Decision

Rebuild the warehouse with a full refresh, recalibrate the seven fingerprints on the
result, and leave the incremental window as it is. The previous content is not preserved.
It was not reproducible from its own inputs, and it left 1.9 million euros unconverted on
rows that had a usable rate available.

## Alternatives I considered

Recalibrating the fingerprints on the existing content and calling the debt settled.
Rejected: it would record as the reference an accidental state that the pipeline can no
longer produce, which is the opposite of what a fingerprint is for. Widening the window to
cover the whole history. Rejected: it turns every daily run into a full recomputation of
three and a half million rows. Scheduling a periodic full refresh. Deferred rather than
rejected: it is the right answer, but choosing a frequency needs a measurement of how often
the rate source publishes late, and that measurement does not exist yet.

## Consequences

A retroactive correction to the rate cache still does not reach facts outside the window,
and nothing detects it. This one was found by rebuilding and comparing, not by a test, and
the same method is the only one that would find the next one. The rebuilt warehouse is
smaller than the one it replaced, 612 MB against 842 MB, because incremental writes never
compact: two replays of a single day put 247 MB back. Compaction belongs in operations, not
in exceptional maintenance.

## Date

2026-08-02
