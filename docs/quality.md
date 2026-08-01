# Data quality

This document states what the pipeline measures, what it guarantees, and what it does
not. Every figure below can be recomputed from this repository alone, without the
warehouse and without running the pipeline: the six CSV files under
`dashboard/snapshot/` are a committed copy of the published tables.

## What arrives, and what survives

Over 118 ingestion dates, from 2026-04-01 to 2026-07-27:

| Measure | Rows |
|---|---|
| Received | 3,588,450 |
| Quarantined as invalid | 34,105 |
| Removed as duplicates | 27,979 |
| Arrived after their event date | 70,677 |
| Reached the fact table | 3,526,366 |

Late rows are not a defect: they are ordinary, they are counted, and they are joined to
the day they belong to rather than the day they arrived.

## What the rows are worth in euros

Conversion status is recorded per row rather than inferred, in five values:

| Status | Rows | Meaning |
|---|---|---|
| `ok` | 1,484,446 | Converted at the rate published for the event date |
| `base_currency` | 1,410,634 | Already in euros; no conversion needed |
| `unavailable` | 281,627 | The currency is not published by the rate source |
| `carried_forward` | 348,526 | Converted at the most recent earlier rate |
| `rate_missing` | 1,133 | No usable rate, so no euro amount |

Three of these five did not exist in the original design. They were added after
measuring that euro rows, absent from the rate table by construction, would otherwise
have left roughly 40 percent of rows silently null. A row with no euro amount always
carries a status explaining why.

## What is guaranteed

These properties are enforced by tests that run on every pull request, and each one has
been seen fail on a defect introduced on purpose.

- **Rows are accounted for.** Received equals valid plus quarantined, per day. Nothing
  disappears between the landing zone and the fact table without appearing in a count.
- **One row per transaction.** Deduplication is deterministic: given the same input, the
  same row wins, and the count of removed duplicates is obtained by subtraction rather
  than by comparing hashes, since duplicates share the winner's hash by construction.
- **No event after its ingestion.** A transaction cannot be recorded as having happened
  after the batch that carried it.
- **Aggregates reconcile with the fact table.** Each of the three aggregates sums back
  to `fct_transactions` on its own grain.
- **Conversion direction is verified against real values**, not assumed from the shape
  of the formula.
- **Every quarantine reason is counted.** A row rejected for a reason that no counter
  tracks would fail the test that checks the reasons add up.
- **A bad day stops the run.** When the quarantined share for a day exceeds a threshold
  passed as a pipeline parameter, publication does not happen.
- **Replaying the most recent day changes nothing.** The whole chain was run twice in a
  row on that day, against the real warehouse and not a sandbox. The landed Parquet file
  came back byte-identical both times, and the ten table fingerprints were unchanged after
  each run.

## What is not guaranteed

- **The data is synthetic.** It is produced by a seeded generator with deliberately
  injected defects. It is realistic in shape, not in origin, and no property here says
  anything about real payment traffic.
- **Rates come from one public source, with no fallback.** When that source is
  unreachable, the run fails rather than inventing a rate.
- **A late correction to the rate cache never reaches old facts.** Conversion reads the
  cache in its current state, but only rows whose ingestion date still falls inside the
  window are recomputed. Filling a gap in the cache four months after the fact left 63,348
  rows carrying a status the cache no longer justified, and nothing detected it until the
  warehouse was rebuilt. Record 0019 has the measurement and the decision.
- **A partition older than the deduplication window is not reconsidered.** The window is
  anchored on the most recent ingestion date, and anything before it is silently out of
  scope.
- **Nothing reverifies the content fingerprints automatically.** They were confirmed once,
  by rebuilding the whole warehouse from unchanged inputs and comparing table by table, and
  that rebuild is what uncovered the conversion drift above. No test repeats it: the check
  costs a full rebuild of three and a half million rows, so it happens when someone decides
  it should.
- **The public dashboard shows a frozen snapshot**, not the live warehouse.

## How to recompute these numbers

Every count in the first two tables comes from two CSV files in this repository:
`dashboard/snapshot/data_quality_daily.csv` for the row accounting, and
`dashboard/snapshot/agg_fx_exposure_daily.csv` for the conversion statuses. Both carry a
header, and `dashboard/snapshot/manifest.json` records each column, its type, its row
count and a content fingerprint of the table it came from.
