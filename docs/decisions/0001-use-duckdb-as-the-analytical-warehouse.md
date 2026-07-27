# 0001. Use DuckDB as the analytical warehouse

## Context

I need a warehouse for the staging and marts layers that dbt will build on top of the
landed daily batches and the cached FX rates. The platform runs as a single batch job on
one machine, not as a shared service with concurrent writers, so I do not need a
client-server database for this stage. I probed DuckDB 1.5.5 directly, and it reads
Parquet with Hive partitioning, filling in the partition column with the correct type
without extra configuration, executes `qualify`, and hashes deterministically with `md5`
across different `PYTHONHASHSEED` values, which matters for a stable `row_hash`. I also
confirmed dbt-core 1.12.0 with dbt-duckdb 1.10.1 can force the session time zone to UTC
from `profiles.yml` and that `delete+insert` on an incremental model replaces rows by
`unique_key` instead of appending them, which is the semantics the staging layer needs.

## Decision

I will use DuckDB as the analytical warehouse for staging and marts, queried in-process
by dbt through dbt-duckdb, with `data/warehouse.duckdb` as the single file. The FX rate
cache already lives there with 720 rows, untouched by any of this probing.

## Alternatives I considered

I considered PostgreSQL, which would give me a real client-server engine and concurrent
writers, but at this scale it adds a server process, a schema migration path, and
network round-trips for no benefit, since nothing else needs to write to the warehouse
concurrently with a batch run.

## Consequences

DuckDB only supports a single writer at a time. This is the reason a separate service
file will later have to own writes to `warehouse.duckdb` while dbt and ad hoc reads stay
read-only during a run; I accept that constraint now because concurrent writers are not
a requirement yet.

## Date

2026-07-27
