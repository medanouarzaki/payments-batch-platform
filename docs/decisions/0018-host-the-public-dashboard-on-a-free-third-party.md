# 0018. Host the public dashboard on a free third party

## Context

A repository someone can read is not the same thing as a dashboard they can click. The
constraint was absolute: no credit card, no cloud account, no paid tier, and no service
that asks for one later.

## Decision

Deploy on Streamlit Community Cloud from `main`, through a second entry point,
`dashboard/streamlit_app.py`, that takes no argument and rebuilds its data from the
committed snapshot. The local entry point keeps its `--serving-path` argument and reads
the published serving file. The two share the view code and nothing else.

## Alternatives I considered

A container on a free tier elsewhere. Rejected: every provider examined asked for a card
before the first deployment. A recorded walkthrough or annotated screenshots instead of a
running application. Kept as the fallback, and the two captures stay in the README either
way, because a sleeping deployment still needs something to show. Serving the warehouse
directly to the public dashboard. Impossible: it is not in the repository.

## Consequences

Three limits, all stated next to the link rather than discovered by a visitor. The
deployment depends on a personal account outside the project. It sleeps after twelve
hours without visitors, and the first visitor after that waits for it to wake. It shows a
frozen snapshot, not the live warehouse. Two entry points also mean the shared code has to
be exercised in both environments, which is why the dashboard test suite covers the
argument-free path as well as the local one, and why the dashboard image deliberately does
not include the public entry point.

## Date

2026-08-02
