# 0004. Find the best schedule with branch and bound over a monotone penalty

**Status:** Accepted. Amended by [0017](0017-plain-forward-checking-and-pruning-on-ties.md) (prune on equal penalties too) and [0024](0024-cheapest-first-value-order-and-workload-bound.md) (prune on a lower bound).

## Context

Many legal schedules exist, and TinyScheg should return the best one according to fairness and preferences.
Enumerating every legal schedule and scoring each is too expensive.

## Decision

Give every schedule state, **including incomplete ones**, a penalty score that **never decreases** as more slots are
assigned: each state's penalty is greater than or equal to its parent state's.

Keep the best complete, legal schedule found so far "in a pocket":

* each new complete, legal schedule replaces the pocket schedule if its penalty is lower, and is discarded
  otherwise;
* any partial schedule whose penalty is already higher than the pocket's is pruned, since no schedule in its branch
  can be better.

## Consequences

* Large parts of the search space can be skipped once a good schedule is found.
* Every penalty component must be monotone over partial schedules (see
  [0005](0005-weighted-sum-of-normalized-penalties.md)).
* An exact penalty must be computed for every state, since its absolute value is compared with the pocket's;
  scores can't be calculated lazily.
* Score changes must be reverted on backtracking (see [0008](0008-undo-through-trail.md)).
