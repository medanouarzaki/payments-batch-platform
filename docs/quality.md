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

Each property below is enforced by tests that run on every pull request, and each has been
seen fail on a defect introduced on purpose. That was checked again on 2026-08-02, one
mutation per property, rather than trusted from the block where each test was written. Two
of the eight properties this section used to list were holding by nothing at all; record
0022 has what was found and what changed.

- **Valid rows reach the fact table.** Every valid transaction identifier ingested inside
  the deduplication window appears in `fct_transactions`. This is checked directly against
  the staging table, because the published accounting cannot check it: the duplicate count
  is a subtraction, so rows lost on the way to the fact table reappear in it as duplicates
  that were never there, and the arithmetic still balances.
- **The published duplicate count is real.** The duplicates reported for a day equal the
  duplicates measurable independently on the staging table for the same day.
- **One row per transaction.** Deduplication is deterministic: given the same input, the
  same row wins.
- **No event after its ingestion.** A transaction cannot be recorded as having happened
  after the batch that carried it.
- **Aggregates reconcile with the fact table.** Each of the three aggregates sums back
  to `fct_transactions` on its own grain.
- **Conversion direction is verified against real values**, not assumed from the shape
  of the formula.
- **Every quarantine reason is counted.** A row rejected for a reason that no counter
  tracks would fail the test that checks the reasons add up.
- **A bad day stops the run.** When the quarantined share for a day exceeds a threshold
  passed as a pipeline parameter, publication does not happen. The gate's four exit paths
  are covered by tests that run the script itself, in a subprocess, against a temporary
  warehouse.
- **Replaying a day changes nothing.** An integration test replays the most recent and the
  oldest of three ingested days, comparing five table fingerprints and five row counts after
  each replay. Separately, and once, the whole chain was run twice in a row against the real
  warehouse: the landed Parquet file came back byte-identical and the ten table fingerprints
  were unchanged. Only the first of those two runs on every pull request.

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
