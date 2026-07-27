# 0002. Partition the landing zone by ingestion date

## Context

Every row carries two dates: `event_timestamp`, when the transaction happened
at the bank, and `ingestion_date`, when this batch landed in the raw zone.
They are not the same date whenever `late_event` shifts a row's event time
into the past. I need to pick one of them to structure the raw storage
layout, because the partition key decides what a rerun of a given day is
allowed to touch.

## Decision

I partition the raw zone by `ingestion_date`, as
`ingestion_date=YYYY-MM-DD`, and I replace a partition's contents in full on
every write for that date. A run for a given ingestion date only ever reads
and writes its own partition, never an older one, which is what makes the
run replayable: rerunning a day is safe because no other partition is in
scope.

## Alternatives I considered

A single file per run, with no partitioning at all, avoids the question but
loses the ability to isolate or replace one day's data without touching
every other day's. I also considered partitioning by `event_timestamp`,
which is tempting because it groups a transaction with the day it actually
happened. I rejected it because it breaks replayability: a transaction that
arrives late has an event date in the past, so landing it would require
reopening and rewriting an already-closed partition from days earlier,
every time a late arrival shows up.

## Consequences

A late transaction lands in the partition of its ingestion date, not its
event date. Reading raw data by event date is therefore never a matter of
listing a partition directory; it always goes through the transformation
layer, which is the only place that can regroup rows by event date once
lateness has been resolved.

## Date

2026-07-27
