# 0016. Treat a missing warehouse as day one in the nightly chain

## Context

The daily chain begins with a preflight check that refuses to run when the warehouse
file is absent. That is correct for a scheduled task: a missing warehouse means
something has gone wrong upstream, and building on top of nothing would hide it. It is
wrong for a fresh runner, where the first day is supposed to create the warehouse. The
first real nightly run failed after ten seconds with `warehouse file not found at
/opt/project/data/warehouse.duckdb`, a container path that does not exist on a GitHub
runner, because the workflow set no `PAYMENTS_*` variable and the check fell back to
its default.

## Decision

The workflow sets the three data path variables to workspace locations, and the
`nightly` target skips the preflight check when no warehouse exists yet, announcing
that it is treating the run as day one. The preflight script itself is unchanged.

## Alternatives I considered

I considered changing the script's hardcoded default path. Rejected: that default is
correct inside the Airflow container, and editing production behaviour to suit a CI
runner is the wrong direction. I considered making the check warn instead of fail when
the warehouse is missing. Rejected: it would remove the guarantee on the scheduled path
too, which is the path that matters.

## Consequences

The nightly chain now has a branch that the scheduled DAG never takes, and only the
nightly workflow exercises it. The local proof of the chain could not have caught this
defect: it redirects the warehouse path to protect the real warehouse, so the variable
was always set and the default path never exercised. A verification that runs in a
different mode than the one where the defect lives proves nothing about that mode.

## Date

2026-08-01
