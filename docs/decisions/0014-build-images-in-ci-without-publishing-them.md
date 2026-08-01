# 0014. Build images in CI without publishing them

## Context

The repository ships two Dockerfiles, one for Airflow and one for the dashboard.
Neither was built by anything automatic. That gap hid a real defect for a full block:
the dashboard image copied `dashboard/data.py`, a file renamed to `loaders.py` when a
module name collided with the `data/` directory, and the image had not been rebuilt
since. The build failed with `failed to calculate checksum of ref ...
"/dashboard/data.py": not found` the first time CI tried.

## Decision

A CI job builds both images from a clean checkout on every pull request and keeps
nothing. No registry, no login, no credentials, no layer cache. The job passes when
both builds succeed and that is the whole of its contract.

## Alternatives I considered

I considered publishing the images to a container registry. Rejected: nothing consumes
them. The Compose stack builds locally from the same Dockerfiles, and publishing would
add a credential to hold and a retention policy to manage in exchange for an artifact
with no reader. I considered caching layers between runs to make the job faster.
Rejected: a cold build is precisely the property being tested, namely that a freshly
cloned repository produces these images. Warming the cache would weaken the check to
save one minute.

## Consequences

The job takes 1 minute 25 seconds, 29 seconds for the dashboard image and 55 for
Airflow, and that cost is paid on every pull request. Nothing verifies that the
Dockerfile's explicit file list matches what actually sits under `dashboard/`; the
build itself is the only thing that will catch the next rename, and it will catch it
late rather than never.

## Date

2026-08-01
