# 0005. Score as a weighted sum of normalized per-worker penalties

**Status:** Accepted. Amended by [0032](0032-flat-penalty-parts.md) (the parts are measured in fixed units, not
normalized to $[0, k]$).

## Context

A good schedule balances several criteria: workers' preferences about who they share shifts with, an even workload,
and sufficient rest between shifts. These need to be combined into a single number that can be compared between
schedules and that never decreases along the search (see [0004](0004-branch-and-bound-with-monotone-penalty.md)).

## Decision

The penalty is the sum of what each worker "thinks" of the schedule, calculated by a per-worker `Scorer`. It has
three components, each normalized per worker:

* **likes/dislikes** — a penalty for sharing a shift with neutral workers (small) or disliked workers (larger);
* **workload** — a fairness penalty on each worker's ratio of assigned hours to available hours
  (see [0006](0006-convex-function-for-workload-fairness.md));
* **rest** — a penalty for each rest period that falls short of a target proportional to the preceding shift's
  length (see [0007](0007-greedy-bound-for-worst-rest-deficit.md)).

The total penalty is their weighted sum, $a \cdot \mathcal{L}^{**} + b \cdot \mathcal{W}^* + c \cdot \mathcal{R}^{**}$
with $a + b + c = 1$, which lies between 0 and the number of workers.

The full specification is in [Scoring](../explanation/scoring.md).

## Consequences

* The relative importance of each criterion is controlled by the weights.
* Each component can be developed and reasoned about separately.
* Each component must be non-negative and monotone over partial schedules.
