# Operations

How the pipeline is run, replayed, and inspected. Everything here assumes a checkout and
nothing else; there is no cloud account and no shared environment.

## Running one day

The whole daily chain runs outside any scheduler with a single command:

```
make nightly
```

It defaults to yesterday in UTC and accepts `DATE=YYYY-MM-DD`. It replays the same nine
steps the scheduled pipeline runs, in the same order, using the same scripts. When no
warehouse exists yet it says so and treats the run as day one rather than failing.

This command writes to whatever `PAYMENTS_WAREHOUSE_PATH` points at, and to the real
warehouse when that variable is unset. Redirect the three data path variables before
running it anywhere you do not want that.

## Running the scheduled pipeline

```
make init-env
make up
```

The first command creates local secrets once: a Postgres password, a Fernet key, and an
admin user; it runs through `uv`, so `make install` has to have happened first. The second
builds the images and starts five services: Postgres, a one-shot container that migrates the
metadata database and creates the admin user and the warehouse pool, the scheduler, the web
server on `http://localhost:8080`, and the dashboard on the port `STREAMLIT_PORT` names —
`http://localhost:8502` by default, and not 8501, because another Streamlit project may
already hold that port. Once the stack has settled, `docker compose ps` lists four of the
five: the initialisation container has done its work and exited, and `docker compose ps -a`
still shows it.

The daily pipeline is created paused and stays paused. Nothing runs until it is
explicitly unpaused or replayed, which is deliberate: automatic catch-up would replay
old days against a rate cache that has moved since.

```
make down
```

stops the stack and removes the metadata volume, so run history does not survive it. The
warehouse and the landed partitions live on the host and are unaffected.

### A second checkout on the same machine

Compose derives its project name from the directory it runs in, and nothing here overrides
that. Two checkouts sitting in directories with the same name are therefore one project as
far as Compose is concerned: same containers, same network, same metadata volume. Since
`make down` runs `docker compose down -v`, running it from the second checkout removes the
first one's metadata volume, and nothing warns you. If a second copy has to run, set
`COMPOSE_PROJECT_NAME` to something else and keep it set for `make up` and `make down`
alike.

## Replaying a range

```
make backfill FROM=2026-04-01 TO=2026-04-30
```

`FROM` and `TO` are required and inclusive. `DRY_RUN=1` previews without executing.
`RESET=1` clears and reruns days that already have a run in the range — it resets every
day in that range, not just the failed one, so pass exactly the range you mean.

Days are replayed in chronological order. Out of order, a later day would set the
deduplication window's anchor ahead of the days still to come, and those days would fall
outside their own window.

## Inspecting

```
make inspect DATE=YYYY-MM-DD
```

reports what a partition contains. The daily chain also ends with a summary step that
prints row counts per published table.

```
make dashboard
```

serves the four views at `http://localhost:8501`, reading the published serving file
rather than the warehouse. It requires `make dashboard-install` once: the dashboard has
its own virtual environment because Streamlit constrains a library version that the
pipeline pins higher.

## Publishing

The serving file is replaced atomically at the end of each successful run. To refresh
the committed CSV snapshot that the public dashboard reads:

```
make snapshot
```

It reads the serving file read-only, writes six CSV files and a manifest under
`dashboard/snapshot/`, and is idempotent: re-running it on unchanged data produces
byte-identical files.

## Compacting the warehouse

Incremental writes never reclaim space. The file grows on every run even when the content
does not change: two replays of a single day added 247 MB to a 612 MB warehouse, and the
118 runs that originally built it had left it 38 percent larger than the same content
occupies once compacted. DuckDB frees the blocks for reuse but never shrinks the file, and
a checkpoint does not either.

Compaction is a copy. Attach a new database file, run `copy from database` into it, verify
the copy against the fingerprints before replacing the original, and keep the original
until that verification has passed. The new file has to be called `warehouse.duckdb`:
DuckDB derives the catalog name from the file name, and `stg_fx_rates` is a view whose
stored definition names that catalog, so a copy under any other name opens but fails on
that view.

Nothing does this on its own. It is a manual operation, and nothing degrades without it
except free disk space.

## When something breaks

**A run stops at the quality gate.** The quarantined share for that day exceeded the
threshold. Nothing was published, which is the intended outcome. Inspect the day's
partition before deciding whether to lower the bar or fix the input.

**The dashboard cannot open the serving file.** DuckDB refuses a reader while a writer
holds the database. Wait for the run to finish; the dashboard is meant to read the
published file, never the warehouse.

**The dashboard shows stale data after a run.** The published file is replaced rather
than edited, so a reader attached to the old file keeps answering from it until it
reopens. Refresh the page.

**A rate fetch fails.** The rate source is a single public API with no fallback. The run
fails rather than converting with a rate it invented. Rerun when the source is back.

**The pipeline is stuck behind a failed day.** The three transformation steps depend on
the previous run of the same step, so a failed day blocks the next rather than building
on a half-written warehouse. Fix the day, then replay forward.

## What would be needed in production

None of this is production. The gaps that matter most, in order: the warehouse is a
single file on one machine with no replication and no backup schedule; there is no alert
anywhere, only exit codes; secrets live in a local file rather than a secret manager; and
the rate source has no fallback, so an outage upstream stops the chain.
