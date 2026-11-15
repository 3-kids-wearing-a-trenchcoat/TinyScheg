# 0014. Calculate the worst rest deficit exactly

**Status:** Accepted. Supersedes [0007](0007-greedy-bound-for-worst-rest-deficit.md). Amended by
[0036](0036-rest-targets-from-the-input-convex-per-worker.md) (each step's target comes from both shifts' lengths) and
[0038](0038-rests-count-only-available-time.md) (each step's rest is counted in available time).

## Context

The rest penalty is normalized per worker by $M_w$, the worst possible rest deficit for that worker, so that each
worker's normalized rest penalty lies between 0 and 1.
[ADR 0007](0007-greedy-bound-for-worst-rest-deficit.md) chose to approximate $M_w$ with a greedy algorithm, as an
upper bound, to avoid calculating it exactly as the heaviest path in a directed acyclic graph (DAG).

But a greedy algorithm finds one *actual* sequence of shifts, whose deficit can only be less than or equal to the
worst case. It gives a **lower** bound, so normalized rest penalties could exceed 1. Meanwhile, the intended schedules
are small (24–48 hours), so each worker has only tens of candidate slots.

## Decision

Calculate $M_w$ **exactly**, as the heaviest path in a DAG whose nodes are the slots in $w$'s domain, with an edge
from $s$ to $s'$ whenever $s'$ starts at least $m$ hours (the minimum rest period) after $s$ ends, weighted by the
deficit it causes, $\max\big(0,\ \gamma\cdot|s| - ([s']_\text{start} - [s]_\text{end})\big)$.
See [Scoring](../explanation/scoring.md#calculating-the-worst-possible-deficit-m_w).

## Consequences

* Each worker's normalized rest penalty is guaranteed to lie in $[0, 1]$, and $\mathcal{R}^{**}$ in $[0, k]$.
* Calculating $M_w$ takes $O(n^2)$ time per worker for $n$ candidate slots, once, before the search. This is cheap at
  the intended schedule sizes. If much larger schedules are ever needed, a cheap *true* upper bound (e.g. the
  maximum number of shifts in a chain times the largest possible deficit per shift) could replace it.
* $M_w$ is computed deterministically, as [ADR 0012](0012-deterministic-path-independent-scoring.md) requires.
