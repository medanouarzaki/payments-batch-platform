# 0021. Lint the singular dbt tests, and keep the layout group excluded

## Context

ADR 0012 excluded the `layout` rule group after measuring 62 violations across the nine
models. Re-measuring at the end of the project returned the same 62: 41 LT02, 19 LT05,
2 LT01. The figure held.

Measuring `dbt/tests` for the first time returned something else. The `lint-sql` target
pointed at `dbt/models` and nothing else, and the CI `lint` job runs that target, so the
sixteen singular tests had never been linted by anything. They carried 15 violations under
the configuration already in force, none from the `layout` group: 10 RF02, 2 ST09, 2 ST07,
1 AM05. Eleven of the fifteen were in `reconciliation_by_ingestion_date.sql`, deleted in
this block for asserting an identity that was true by construction. Four remained.

## Decision

`make lint-sql` lints `dbt/models` and `dbt/tests`. The four remaining violations are
fixed: join references qualified, `USING` replaced by `ON`, join members reordered. None of
those edits changes what a test asserts, and the full dbt build stayed green through them.
`exclude_rules = layout` stays as it is.

## Alternatives I considered

Reformatting the models to satisfy the layout group. Rejected for the reason ADR 0012 gave,
now with a second one behind it: those models produce the ten reference fingerprints this
project checks itself against, and 62 mechanical rewrites against them buy nothing that
anyone reading the SQL would notice.

Leaving `dbt/tests` out of the linter, on the grounds that tests are not production code.
Rejected: the singular tests are the assertions this project advertises. They are the last
place where a silent defect should be allowed to sit.

## Consequences

The layout debt is now a measured number rather than an inherited assumption, and it is
written here: 62 violations, nine models, revisit if the SQL surface grows. A violation
introduced in a new singular test now fails CI, which is what the previous arrangement could
not do.

## Date

2026-08-02
