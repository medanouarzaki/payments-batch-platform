# 0008. Run Airflow locally with Docker Compose

## Context

The pipeline needed a real scheduler to prove that daily runs, backfills,
and a quality gate behave the way the dbt models and the test harness
already assume, rather than staying a hypothesis exercised only through
pytest fixtures. The project runs on a single machine with no shared
infrastructure to deploy against, and the goal was to observe Airflow's own
scheduling behaviour — `depends_on_past`, pools, backfill semantics — not to
operate a production instance.

## Decision

Airflow 2.11.2 runs with the local executor, wired up through Docker
Compose: one Postgres container for the metadata database, one init
container that migrates the schema and creates the admin user, a scheduler,
and a webserver exposed on port 8080. Because dbt needs a duckdb version
newer than the one Airflow's own pinned dependency set ships with, dbt runs
in a separate Python virtualenv baked into the Airflow image rather than in
Airflow's own site-packages. A single-slot pool named `warehouse` serializes
every task that touches the DuckDB file, since DuckDB does not support
concurrent writers.

## Alternatives I considered

A managed orchestrator such as Cloud Composer or MWAA would remove the need
to operate Postgres and the scheduler by hand, but it requires an account
with a cloud provider and recurring cost for a project meant to run
entirely on a laptop. Rejected for now: the goal here is to observe
scheduling behaviour locally, not to operate a hosted service. I also
considered a plain system cron job invoking the existing CLI commands
directly, which would have avoided Airflow entirely. Rejected because it
cannot express `depends_on_past` or backfill semantics, and those are
exactly the behaviours this block needed to exercise and measure.

## Consequences

The stack is heavier to start than a single Python process: three
containers must reach a healthy state before a DAG can run, and a fresh
environment needs `make init-env` to generate local secrets before anything
else works. The separate dbt virtualenv is an extra piece of image-build
logic to maintain whenever either dbt's or Airflow's dependency pins move.
I accept both costs because they buy an orchestrator that behaves like the
one a real deployment would use, which is what let this block's backfill
and quality-gate work be verified against actual scheduling behaviour
instead of a simulation of it.

## Date

2026-07-29
