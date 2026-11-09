# 0010. Rewrite in Python

**Status:** Accepted

## Context

An earlier iteration of TinyScheg was written in Java (December 2024 to January 2025), with separate `CSP` and
`Scheduler` packages. It was never completed. The reasons for moving away from it weren't recorded.

## Decision

Rewrite TinyScheg in Python. The Java code was removed from the repository on 2025-10-21, and the Python
implementation was started from scratch.

## Consequences

* The Java code remains available in the repository's git history.
* Notes describing the Java iteration don't describe the current design.
