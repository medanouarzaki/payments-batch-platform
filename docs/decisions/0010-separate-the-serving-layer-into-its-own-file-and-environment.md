# 0010. Separate the serving layer into its own file and environment

## Context

The warehouse is a single DuckDB file, `data/warehouse.duckdb`, opened while
dbt or the CLI write to it. The dashboard needs the same aggregates without
competing for that file. A measurement in this block showed why sharing it
directly is not viable: with a writer holding the file open, publication
fails with `IOException: Could not set lock on file`, reporting a conflicting
lock held by another process, while a concurrent reader does not block
publication at all. A second constraint sits outside DuckDB entirely:
installing the dashboard's dependencies with `uv sync` for the `dashboard`
group downgraded `pyarrow` from 25.0.0 to 24.0.0 in the main environment,
because Streamlit 1.60.0 constrains `pyarrow` below 25 while the pipeline
requires 25.0.0 for Parquet writes.

## Decision

The daily DAG publishes a separate DuckDB file under `data/serving/`, written
atomically by replacing the file rather than editing it in place, and the
dashboard runs in its own virtual environment, `.venv-dashboard`, isolated
from the pipeline's dependency set. The dashboard opens the serving file
read-only and never opens `data/warehouse.duckdb`, so the two processes
never contend for the same lock. The serving file currently holds six
tables in 1,847,296 bytes.

## Alternatives I considered

I considered having the dashboard read `data/warehouse.duckdb` directly in
read-only mode. Rejected: DuckDB's lock is exclusive per file regardless of
the reader's own mode, so a reader would still fail whenever the pipeline
held the file for writing, which is precisely the failure this block
measured. I also considered installing the dashboard into the pipeline's
own virtual environment. Rejected because Streamlit's `pyarrow` constraint
would then downgrade the version the pipeline's Parquet writes depend on.

## Consequences

The dashboard never shows the warehouse's current state, only the content
of the last successful publication; a reader already attached to the file
when it is replaced keeps answering from the old inode until it reopens the
file, a behaviour a container-mount check in this block also exercised,
alongside a read-only mount rejecting a write with
`Read-only file system`. The serving file duplicates data already present
in the warehouse, and its byte layout is not a stable invariant across
republications, only its content fingerprint is, as this block established.
The dashboard's own code is not covered by any CI pipeline today. I accept
these costs because they buy a dashboard that never competes with the
pipeline for the one resource DuckDB cannot share.

## Date

2026-07-30
