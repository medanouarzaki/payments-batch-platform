# Data model

This document describes the raw transaction data produced by the generator and
landed by the ingestion module, as the code behaves today. Every number, column
name, and rate below was read from a command against this repository; none is
carried over from memory or from an earlier description of the project.

## The raw contract

`payments.generator.schema.RAW_COLUMNS` defines fourteen columns, in this
order: `transaction_id`, `event_timestamp`, `amount`, `currency`,
`debtor_account`, `creditor_account`, `debtor_country`, `creditor_country`,
`status`, `rejection_reason`, `channel`, `source_batch_id`, `ingested_at`,
`ingestion_date`.

Twelve of the fourteen are strings, and every one of the twelve is nullable.
`ingested_at` is the single exception among the data columns: a timezone-aware
UTC `datetime`. `ingestion_date` is a plain `date`. A row produced by
`generate_batch` looks like this:

| Column | Value |
|---|---|
| transaction_id | `TXN-2026-06-01-84209855` |
| event_timestamp | `2026-06-01T15:26:37Z` |
| amount | `181.91` |
| currency | `CAD` |
| debtor_account | `FR4960228837816086913731387` |
| creditor_account | `NL6947037703727636` |
| debtor_country | `FR` |
| creditor_country | `NL` |
| status | `ACCEPTED` |
| rejection_reason | `None` |
| channel | `TRANSFER` |
| source_batch_id | `BATCH-20260601-01` |
| ingested_at | `2026-06-01 23:59:59+00:00` |
| ingestion_date | `2026-06-01` |

`amount`, `event_timestamp`, and both country codes hold values that look
numeric, temporal, or categorical, and yet none of them is typed as such. This
is deliberate: the contract carries whatever text a payments network handed
over, without pretending to have already interpreted it. Parsing an amount,
resolving a country code, or deciding whether a timestamp is trustworthy is
work performed by a downstream transformation layer, over data whose contract
has not silently narrowed those decisions away. The defect catalogue below
depends on this: several defects only exist as distinguishable states because
the column that carries them is still a string.

## What the file actually contains

The Parquet file written by `land_batch` carries thirteen columns, not
fourteen: `ingestion_date` is excluded from `PARQUET_SCHEMA` and is never
written into the file. It is recovered instead from the partition directory
name, `ingestion_date=YYYY-MM-DD`. Reading `pq.read_schema()` against a landed
file gives this, in file order:

```
transaction_id string
event_timestamp string
amount string
currency string
debtor_account string
creditor_account string
debtor_country string
creditor_country string
status string
rejection_reason string
channel string
source_batch_id string
ingested_at timestamp[us, tz=UTC]
```

A query against the partition root with `hive_partitioning = 1` reconstitutes
the fourteenth column from the directory name and returns it typed as `DATE`,
equal to the run date the batch was generated for. Every column, including
ones that happen to be entirely `NULL` in a given batch, is written with an
explicit type rather than one inferred from the row values: `PARQUET_SCHEMA`
is passed to `pa.Table.from_pylist` on every write. A column that is all
`NULL` in a particular batch has no values from which to infer a type, and an
inference-based table build assigns it `null` or a coincidental type such as
`INTEGER`, which then breaks a later read that expects `VARCHAR`.

## Injected defects

`load_defect_rates()` reads `config/defects.yml`. The rates below are copied
from that command's output, not from the YAML source directly:

| Defect | Rate | Produced form | Downstream treatment |
|---|---|---|---|
| `late_event` | 0.02 | `event_timestamp` set to a day between 1 and 5 days before `ingestion_date`; example: an event timestamp of `2026-05-28T12:20:10Z` inside a batch whose `ingestion_date` is `2026-06-01` | Normalization: the row is a legitimate transaction with a late arrival, tagged rather than removed |
| `naive_timestamp` | 0.08 | `event_timestamp` without a timezone indicator, e.g. `2026-06-01T12:39:02` | Normalization: the offset is inferred as UTC and the string reparsed |
| `offset_timestamp` | 0.10 | `event_timestamp` with a space separator and a non-UTC offset, e.g. `2026-06-01 21:11:18+05:30`; the underlying instant is unchanged | Normalization: converted back to UTC before use |
| `missing_currency` | 0.004 | `currency` set to `None` or `""` | Quarantine with a reason code: no currency can be assumed for a payment |
| `unknown_currency` | 0.002 | `currency` set to `XXX` or `ZZZ`, e.g. `XXX` | Quarantine with a reason code: not a currency this platform recognizes |
| `lowercase_currency` | 0.01 | `currency` lowercased, e.g. `pln` | Normalization: uppercased before use |
| `non_positive_amount` | 0.003 | `amount` set to `0.00` or a negative value, e.g. `-378.31` | Quarantine with a reason code: not a valid payment amount |
| `amount_formatting` | 0.01 | `amount` reformatted with a comma decimal separator and space thousands separator, e.g. `66,01`, numeric value unchanged | Normalization: reparsed back to a dot-decimal string |
| `malformed_country` | 0.015 | one of `debtor_country` or `creditor_country` set to a lowercase, alpha-3, spaced, `ZZ`, or `None` form | Quarantine with a reason code: not every variant is safely reversible |
| `missing_transaction_id` | 0.0005 | `transaction_id` set to `None` | Quarantine with a reason code: no stable identity to join or deduplicate on |
| `duplicate_exact` | 0.005 | a byte-for-byte copy of an existing row, sharing its `transaction_id` | Deduplication: keep one instance of the pair |
| `near_duplicate` | 0.003 | a copy sharing `transaction_id` with an existing row, differing in `status` or `amount`, with a later `event_timestamp`; example: one row `ACCEPTED` at `35.47` and another under the same `transaction_id` `ACCEPTED` at `75.04` | Deduplication: keep one instance, chosen by a tie-breaker such as latest `event_timestamp` |

`late_event.min_days` and `late_event.max_days` in the same file are `1` and
`5`: the shift applied by `late_event` is a whole number of days drawn from
that range.

## Mutually exclusive families

Three of the twelve defects group into families whose members cannot both
land on the same row: currency (`missing_currency`, `unknown_currency`,
`lowercase_currency`), amount (`non_positive_amount`, `amount_formatting`),
and timestamp (`naive_timestamp`, `offset_timestamp`). Each family resolves
with a single draw per row, compared against the members' cumulative
thresholds in the order listed above, using one random generator per family.
Within a family, changing one member's configured rate shifts where the
threshold boundaries fall for the other members, so their observed
attribution shifts too, even though each member's own probability stays
correct. Across families, and for the defects that sit outside any family
(`late_event`, `malformed_country`, `missing_transaction_id`,
`duplicate_exact`, `near_duplicate`), the random streams are independent:
each has its own generator, and none of them is affected by a rate change to
a defect it does not share a family with.

## Determinism

Every generator and defect stream is seeded through SHA-256 over a string
built from the batch seed, the run date, and (for family and defect streams)
a fixed name identifying that stream, then truncated to 64 bits and fed to
`random.Random`. Python's built-in `hash()` is never used for this: `hash()`
is salted per process by default and produces a different value on every
interpreter invocation, so two runs of the same seed and date diverge under
it. SHA-256 has no such salt: the same inputs always produce the same seed.

Two invocations of `payments generate` for the same date, rows, and seed
produce byte-identical Parquet files. Two runs of `--date 2026-06-01 --rows
5000 --seed 42` in this session both landed a file with the SHA-256
`40a5b7c84c39d39fa68b4cf5985bbf3ac3b7fcbbbe883fac675afd6db06b697a`.

## Landing

`land_batch` writes into a Hive-style partition directory,
`<raw_transactions_dir>/ingestion_date=<run_date>`, and always replaces the
partition's contents in full: nothing is ever appended to an existing
partition. The write itself proceeds in three steps. First, the new data is
written to a temporary file inside the partition and fully flushed. Second,
`os.replace()` moves that temporary file onto the final path,
`part-0000.parquet`, in a single atomic filesystem operation, so the final
path points at either the complete old file or the complete new file and at
no point in between. Third, and only after that swap has landed, anything
else the partition held is removed. This ordering guarantees that a failure
during the final cleanup step leaves the partition holding the new data, not
the old data and not an empty directory: the only state that can be lost to
an interruption is whatever the cleanup step had not yet reached, never the
just-written file itself.

## Volumes

A batch generated for `2026-06-01`, a Monday, produced 39,559 rows before
defect injection and 39,857 after (duplicates and near-duplicates add rows).
Landing it took a `duration_s` of 1.09 and produced a 2,768,258-byte Parquet
file. The same generator run for `2026-05-31`, a Sunday, produced 15,819 rows
before injection and 15,940 after, landed in 0.42 seconds: the weekday
weighting built into the generator's row-count model visibly lowers weekend
volume. A 40,000-row batch written to Parquet came to 2,796,653 bytes; the
same rows written to CSV came to 6,953,057 bytes, 2.486 times the Parquet
size.
