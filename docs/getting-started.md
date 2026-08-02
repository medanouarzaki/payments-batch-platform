# Getting started

This walks the shortest path from a clone to a dashboard you can look at: one generated day
of transactions, processed end to end, on your own machine. It takes about six minutes, most
of which is the test suite. Nothing here needs Docker; the orchestrated version lives in
`docs/operations.md`.

Timings were measured on an Apple M3 with an empty package cache. A warm cache is faster.

## Before you start

You need Python 3.11, [uv](https://docs.astral.sh/uv/), `git`, `make`, and about 1.6 GB of
free disk: 840 MB for the clone and its virtual environment, and roughly 760 MB more for
uv's download cache, which is shared with your other projects.

You also need to be online for `make nightly`: exchange rates come from a public API and
the run fails rather than inventing a rate when that source is unreachable.

## The five steps

```
git clone https://github.com/medanouarzaki/payments-batch-platform.git
cd payments-batch-platform
```

**`make install`** — 12 s, 762 MB downloaded. Creates `.venv/` in the project, about
435 MB, and installs the `payments` package into it. If your shell has another virtual
environment active, uv prints a warning saying it will be ignored; that is correct
behaviour and nothing is wrong.

**`make test`** — 4 min 34 s, 191 tests, 95.4% coverage of `src/payments/`. The integration
tests build whole dbt projects, but each one works in its own temporary directory: this step
writes nothing under `data/`.

**`make nightly`** — 8 s on a fresh clone. This is the whole daily pipeline, replayed
outside any scheduler. It generates one day of transactions, lands them as Parquet under
`data/raw/transactions/`, creates `data/warehouse.duckdb`, runs the dbt models and their
tests, checks the day against the quality gate, and publishes `data/serving/marts.duckdb`.

On a fresh clone there is no warehouse, so the run takes the day-one branch and every model
builds from scratch. On a machine that already holds a warehouse it replays the most recent
ingestion date instead, doing incremental work against existing tables, and costs about
12 s. Both are normal; only the first is what a new clone sees.

**`make dashboard-install`** — 11 s. Creates a second virtual environment, `.venv-dashboard/`.
There are two because Streamlit 1.60 requires `pyarrow < 25` while the pipeline pins 25.0.0.
`uv sync` does not create this one; this target does.

**`make dashboard`** — prints `http://localhost:8501` and waits. It does not open a browser:
`.streamlit/config.toml` pins the server to headless mode, which also means a first launch
on a machine where Streamlit has never run does not stop on its welcome prompt. Stop it with
Ctrl-C.

## When something does not behave

**The dashboard opens but has no data.** It reads `data/serving/marts.duckdb`, which
`make nightly` publishes. Run that first.

**Port 8501 is already in use.** Another Streamlit is running. `lsof -ti tcp:8501` names the
process.

**`make nightly` fails on rates.** The API is unreachable, or you are offline. The run is
supposed to fail here rather than carry a rate it cannot justify.

**You already have a warehouse and do not want to touch it.** `make nightly` writes to
`data/warehouse.duckdb` under the project root unless `PAYMENTS_DATA_DIR`,
`PAYMENTS_RAW_TRANSACTIONS_DIR` and `PAYMENTS_WAREHOUSE_PATH` point elsewhere. Inside the
`payments` package those variables are read in exactly one place, `src/payments/config.py`.
The scripts under `airflow/scripts/` are the exception: they read `PAYMENTS_WAREHOUSE_PATH`
themselves, because they run under the Airflow image's interpreter rather than the project
environment.

## Where to go next

- `docs/architecture.md` — every model, every edge, and what runs where.
- `docs/operations.md` — the Airflow stack, replaying a day, and what to do when a run
  breaks.
- `docs/quality.md` — what the numbers are, what is guaranteed, and what is not.
- `docs/decisions/` — twenty-two records of what was chosen and what was rejected.

## When the install fails

`make install` leans on a service it does not pin. `uv.lock` records every dependency with
its hash, and `dbt-core-experimental-parser` is in there like the rest — but that package
ships as a source distribution only, and its build step fetches a prebuilt wheel from a
GitHub release page. The lock file says nothing about that fetch.

Here is what it looks like when it goes wrong. `uv sync` stops partway through with a
`RuntimeError` naming a `github.com` URL and an HTTP error, most often a 503. Nothing is
half-installed in a way that needs cleaning up, and nothing on your side caused it. Run
`make install` again.

There is a way to close this, by pinning or vendoring a prebuilt wheel, and it is not done
here. It would change the install path for everyone who clones this repository, which is a
larger change than the failure it prevents.
