# 0020. Run the nightly chain twice in CI

## Context

The `nightly` target calls three task scripts that read the warehouse path from the
environment and fall back to the Airflow container's path when it is absent. The recipe
computed that path for its own use but never exported it, so on any machine where the
warehouse already exists the chain stopped at the first script with `warehouse file not
found at /opt/project/data/warehouse.duckdb`.

It passed everywhere it ran. The CI runner starts empty, so it takes the day-one branch
that skips the check entirely. Inside the container the fallback path is the correct one.
Local verification always redirected the variable in order to protect the real warehouse.
The defect lived in the one mode nothing exercised, and it had been there since the target
was written.

## Decision

The recipe exports both data path variables, derived from `config.py`, before calling
anything, which also removes the second source of truth it kept for its own file test. The
nightly workflow runs `make nightly` twice: once on an empty warehouse, then again against
the warehouse the first run built.

## Alternatives I considered

A unit test on the recipe. Rejected: it would either assert on the text of the Makefile,
which says nothing about behaviour, or run the chain for real, which needs the rate source
and would make a test depend on the network. Changing the scripts' default paths. Rejected
for the same reason as in 0016: that default is correct inside the container. Relying on
the local replay. That is precisely what failed.

## Consequences

The nightly job takes about twice as long, which is a matter of seconds, and the populated
branch is now exercised on a clean machine every night. Record 0016 already stated the
general lesson, that a check running in a different mode than the one where the defect
lives proves nothing about that mode. This defect confirms it from the other side: the fix
recorded there is what created the day-one branch that hid this one.

## Date

2026-08-02
