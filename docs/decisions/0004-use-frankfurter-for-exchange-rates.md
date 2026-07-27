# 0004. Use Frankfurter v1 for exchange rates

## Context

The payments batch needs a daily EUR-based rate for eight currencies,
cached in DuckDB so a run never depends on network availability at read
time. I looked for a source that needs no API key, no card on file, and
whose numbers I can trace to a named authority rather than to an
aggregator's own blending.

## Decision

I use Frankfurter's v1 surface, backed directly by European Central Bank
reference rates, with no key required. I query v1 rather than v2, even
though v2 is Frankfurter's current surface and, unlike v1, does publish
MAD: the reason is that v1 is a single source with one documented
methodology I can audit end to end, while v2 blends several providers
behind one endpoint and a response does not tell me which provider's
number I am looking at for a given day. v1 is marked superseded by v2; if
v1 disappears, moving to v2 means adopting its blended-provider model and
re-deriving, currency by currency, what is actually published day to day,
not just changing a base URL. I verified the upsert path empirically
rather than trusting DuckDB's documentation: I ran an `INSERT ... ON
CONFLICT DO UPDATE` against a throwaway database on duckdb 1.5.5 before
writing the cache module, and only built the cache around it once I had
seen the row get replaced rather than duplicated. The cache degrades
rather than fails: a row left behind by a failed fetch carries a reason
distinct from a currency the API has confirmed it does not publish, so
only the unknown case is retried on the next run while the confirmed case
stops looping.

## Alternatives I considered

exchangerate.host and Fixer both gate historical lookups behind a paid
key at the volume this project needs. The European Central Bank's own raw
XML feed is free but exposes only the latest day and a fixed ninety-day
window as flat files, pushing date-range matching back onto me instead of
the API doing it.

## Consequences

A rate whose effective date falls more than seven days behind the date
requested is treated as unavailable rather than substituted, so that date
has no conversion at all until a later backfill fills the gap by hand.

## Date

2026-07-27
