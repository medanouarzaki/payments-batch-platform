# 0003. Generate synthetic transactions instead of using a public dataset

## Context

This project needs to demonstrate handling of dirty payment data: missing
currencies, malformed country codes, late-arriving events, duplicates. To
build and test that handling, I need a source of transactions where I both
control which defects appear, at what rate, and can point at the exact rows
that carry each one.

## Decision

I generate synthetic transactions with my own generator, seeded
deterministically from a batch seed and the run date, and I inject each
defect independently at a configured rate read from `config/defects.yml`.
Two runs of the same seed and date produce the same batch, byte for byte,
which lets a test assert on an exact row count for a given defect rather
than an approximate one.

## Alternatives I considered

A public transactions or fraud-detection dataset would have realistic
value distributions and correlations, which synthetic data does not. I
rejected it because none of the public datasets I am aware of let me
choose that 0.4% of rows have a missing currency and 1.5% have a malformed
country code, or point at which specific rows those are; the defect rates
and their ground truth are exactly what the project needs to control. An
anonymized extract from a real processor has the same problem, plus
licensing and personal-data handling that a demonstration project has no
reason to take on.

## Consequences

The generated data has no real structure: no seasonal pattern a forecast
model could pick up, no correlation between channel and amount, nothing
that reflects how payment volumes actually behave. This project
demonstrates the data platform, the injection, landing, and downstream
handling of dirty records, and not any analysis of real payment behavior.
Anyone using this data to validate a business-facing model or dashboard is
using it for something it was not built to support.

## Date

2026-07-27
