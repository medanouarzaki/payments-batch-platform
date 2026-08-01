# 0017. Commit the public snapshot as CSV

## Context

The public dashboard runs on a platform that builds from a branch of this repository.
It cannot reach the warehouse or the serving file: neither is committed, and the
warehouse is hundreds of megabytes. Something published has to carry the data, and that
something has to be reviewable, since it is the only copy a reader can inspect without
running anything.

## Decision

Six CSV files and a JSON manifest under `dashboard/snapshot/`, committed. The manifest
records, for each table, its row count, its content fingerprint, the CSV file that holds
it, and the ordered list of its columns with their types. The public entry point rebuilds
an in-memory database from the manifest rather than letting the CSV reader guess.

## Alternatives I considered

Committing the serving file itself. Rejected: a binary rewritten on every publication
makes the history grow without being reviewable, and nobody can see what changed between
two versions. Attaching it to a release instead. Rejected: it separates the data from the
commit that produced it, and adds a download step to the dashboard's start-up. Letting
DuckDB infer the column types when reading the CSV. Rejected after measuring that five of
the fifty-three columns would be guessed wrong, including all four amount columns, which
would come back as DOUBLE instead of DECIMAL. The manifest exists because of that
measurement.

## Consequences

The snapshot is diffable, and that pays: rebuilding the warehouse changed 236 lines
across three of the six files, visible in review, while the three unaffected files stayed
byte-identical. The cost is that the repository carries a duplicate of the published data,
and that nothing refreshes it. `make snapshot` is manual, so the public dashboard shows
whatever state was last committed.

## Date

2026-08-02
