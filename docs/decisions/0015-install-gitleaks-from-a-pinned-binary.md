# 0015. Install gitleaks from a pinned binary rather than an action

## Context

The repository is public and its history contains a Compose setup that consumes a
Postgres password, a Fernet key and an admin password. Those values live in a `.env`
file that is ignored, but nothing proved they had never been committed. A scan of the
full history takes 165 milliseconds locally across 142 commits and 514 kilobytes, so
there is no reason to scan anything narrower than everything.

## Decision

The CI job downloads a version-pinned gitleaks release archive by URL and runs the
binary. No third-party action is involved. The scan covers the complete history on
every pull request, not the diff.

## Alternatives I considered

I considered the official gitleaks action. Rejected: every third-party action is a
dependency to pin by commit hash, audit and keep current, and this one wraps a single
binary invocation. Downloading the release directly leaves the version visible in the
workflow file rather than behind a tag. I considered scanning the pull request diff
and reserving the full history for the default branch. Rejected: at 165 milliseconds
there is nothing to optimise, and two modes would mean two behaviours to reason about.

## Consequences

A new gitleaks version has to be adopted by editing a URL, which will not happen
automatically. The job has never been seen red in CI, only locally, because proving it
would mean pushing a credential-shaped string to a public repository; the job is a thin
wrapper around the same binary and the same command that were seen red locally, so I
accept the asymmetry. Building a witness that actually triggers detection was harder
than expected: the first candidate contained ordinary English words, which lowered its
entropy below the rule threshold.

## Date

2026-08-01
