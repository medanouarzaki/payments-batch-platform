# 0012. Exclude the layout rule group from sqlfluff

## Context

Adding sqlfluff to the project reported 166 violations across the nine dbt models on
its default settings. Raising the line limit to 100 characters, the width the rest of
the repository already uses, brought that to 104. Of what remained, 62 belonged to the
`layout` group: indentation, alignment, blank lines, comma position. The other 27 were
about the SQL itself, and five survived scrutiny. The models were written by hand over
seven blocks, and their formatting is consistent enough to read but not consistent
enough to satisfy an opinionated layout engine.

## Decision

`exclude_rules = layout` in `.sqlfluff`. The linter enforces structure, references,
aliasing and capitalisation on every model; it says nothing about whitespace. Three
remaining violations are annotated with `noqa` and the reason each is accepted.

## Alternatives I considered

I considered running `sqlfluff fix` over the layout group and taking whatever it
produced. Rejected: 62 mechanical rewrites across nine models would have made the
diff of this block unreadable, and one automatic fix in this project already violated
a rule it had been told to leave alone, writing an alias in uppercase against the
project's own lowercase convention. I also considered disabling individual layout
rules as they appeared. Rejected: that is the same exclusion, spread over a list that
would grow every time a model is touched, and harder to see at a glance.

## Consequences

A genuine formatting defect in a future model will not be caught. This is a wide
exclusion and it should be revisited if the SQL surface grows: enabling the group on
new models only, or accepting one large mechanical reformat, are both reachable from
here. What the linter does still guarantee is worth having on its own, and it has
already caught a reversed join condition.

## Date

2026-08-01
