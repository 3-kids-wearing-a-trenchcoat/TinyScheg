# 0011. No output for infeasible inputs

**Status:** Accepted

## Context

The input may be over-constrained: too few workers, too much unavailability, or role requirements no one can meet.
In that case no schedule satisfies every hard constraint, and the search proves that no solution exists.

The scheduler could try to degrade gracefully, for example by leaving some slots unfilled or relaxing the minimum
rest period. But an unsolvable schedule is usually something to resolve outside the scheduler: by adding workers,
relaxing role requirements, or closing a post for a while. Those are decisions for whoever is responsible for the
schedule, not for the algorithm.

## Decision

If no legal schedule exists, TinyScheg reports that the input has no solution and produces **no output**.
TinyScheg never relaxes hard constraints on its own; relaxing them is up to the user.

## Consequences

* Every schedule TinyScheg outputs satisfies all hard constraints.
* The search must be able to prove infeasibility, i.e. exhaust the search space. For the intended schedule sizes
  (24–48 hours) this is acceptable.
* Telling the user *why* the input is infeasible would make it much easier to fix. This is not part of this decision;
  see [Future work](../explanation/future-work.md#explaining-infeasibility).
