# 0013. Set a blocking coverage floor at 90 percent

## Context

Test coverage of `src/payments/` measured 95.12 percent when the floor was introduced:
943 statements, 46 uncovered. Coverage had never been measured before, and nothing
stopped it from falling. A number that is only ever reported is a number nobody
notices moving.

## Decision

`fail_under = 90` under `[tool.coverage.report]` in `pyproject.toml`, so `make test`
exits non-zero below it, locally and in CI alike. The threshold sits below the measured
value, not at it.

## Alternatives I considered

I considered setting the floor at the measured value, 95 percent. Rejected: it would
turn every legitimate refactor that adds a branch into a red build, and the pressure
would be to write a test that covers the line rather than one that tests the
behaviour. I considered reporting coverage without failing on it. Rejected: that is
what was already happening in effect, and it caught nothing. I considered enforcing
coverage per module rather than globally. Rejected as premature for a package of
twenty modules where the uncovered lines are concentrated in error paths.

## Consequences

Measuring coverage costs 41 seconds on a test job that already runs for nine minutes.
The five-point gap between the floor and the current value is deliberate slack, and it
means a real regression of four points would pass unnoticed. The floor was seen red
once, on purpose, by leaving an 80-statement module untested: coverage fell to 87.68
percent and the build failed, which is the only reason I believe it works.

## Date

2026-08-01
