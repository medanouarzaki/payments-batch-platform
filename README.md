# Payments batch platform

[![ci](https://github.com/medanouarzaki/payments-batch-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/medanouarzaki/payments-batch-platform/actions/workflows/ci.yml)

Daily extracts from a payment system arrive late, duplicated, and inconsistently
typed.

## Architecture

## Running it

The local stack is Airflow (local executor) plus Postgres for its metadata
database, run through Docker Compose; dbt runs against a DuckDB warehouse
file on the host, mounted into the containers.

On a fresh checkout, generate the local secrets Compose needs (a Postgres
password, an Airflow Fernet key, and an admin user) once:

```
make init-env
```

Then start the stack:

```
make up
```

This builds the Airflow image, migrates its metadata database, and starts
the scheduler and webserver. The webserver is reachable at
`http://localhost:8080` once its health check passes; sign in with the
admin user created by `make init-env`. The `payments_daily` DAG is created
paused, so nothing runs until it is explicitly unpaused or backfilled.

To run or replay a range of days without unpausing the DAG, use the
backfill target:

```
make backfill FROM=2026-04-01 TO=2026-04-30
```

`FROM` and `TO` are required and inclusive. Add `DRY_RUN=1` to preview the
run without executing it, or `RESET=1` to clear and rerun days that already
have a DagRun in the given range — only pass `RESET=1` for the exact range
you mean to redo, since it resets every day in that range, not just a
failed one.

Stop the stack with:

```
make down
```

This also removes the Postgres volume, so Airflow's run history does not
survive it; the DuckDB warehouse and landed partitions live under `data/`
on the host and are unaffected.

## Design decisions

## What broke
