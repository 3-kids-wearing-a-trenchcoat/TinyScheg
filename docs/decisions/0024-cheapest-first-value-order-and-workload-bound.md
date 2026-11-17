# 0024. Speed up branch and bound: cheapest-first value order and a lower bound on workload

**Status:** Accepted. Amended by [0040](0040-workload-bound-in-whole-slots.md) (the workload bound is also taken in
whole slots) and [0045](0045-rest-lookahead.md) (a rest look-ahead).

## Context

Branch and bound ([ADR 0004](0004-branch-and-bound-with-monotone-penalty.md)) runs to the end with no limit. On the
24-hour example it took about 3½ minutes (17 slots), and inputs where workers do several shifts each, the ones the
[schedule audit](../explanation/schedule-audit.md) has something to say about, mostly took longer than 4 minutes. That
made [tuning the scoring](../explanation/tuning.md) impractical: the informative inputs were out of reach. Two causes:

* **A weak bound.** A branch was pruned when its penalty so far reached the pocket's. But the workload penalty barely
  grows until the last slots are filled, so most branches survived until deep in the tree.
* **No value order.** [ADR 0003](0003-variable-ordering-mrv-degree.md) decided that the order workers are tried in
  doesn't matter, since every solution is considered. That's true of the *result*, but how much is pruned depends on
  how good the pocket already is, and workers in input order found good schedules late.

Both were prototyped and measured on 2026-11-11 (see [Future work](../explanation/future-work.md#search-performance)),
and checked against trying every schedule on small inputs.

## Decision

* **Cheapest-first value order** when looking for the best schedule: a slot's workers are tried in order of the
  penalty of the schedule with them assigned, ties in input order. When looking for the first legal schedule, workers
  are still tried in input order. This amends ADR 0003's "no value ordering": the result is the same best penalty, and
  only which of several equally good schedules is kept can change (the first found, in the new order), so the result
  stays deterministic.
* **Prune on a lower bound** instead of the penalty so far: the likes and rest penalties so far, which filling slots
  never lowers, plus the lowest workload penalty the remaining hours could give. Each worker's workload term is
  convex, so the remaining hours give the least penalty when they top up the least-loaded workers who could still
  take some slot to a common level of hours per available hour (water-filling, by Jensen's inequality). Which worker
  can take which slot is ignored, so the bound may be below anything reachable, but never above. A branch is pruned
  when the bound is at least the pocket's penalty, ties included as in ADR 0017. This amends ADR 0004, which prunes
  on the penalty itself.

## Consequences

* The same best penalty as before, found and proven sooner. Every brute-force test still passes, and a test checks
  that the bound is never above the penalty of any legal completion, nor below the partial schedule's own.
* Each node costs more: a penalty per candidate worker for the value order, and the bound instead of the penalty.
* The bound is computed in floating point like the penalty, from scratch and in a fixed order, so it's
  deterministic; rounding could only matter for schedules within about $10^{-15}$ of the pocket, which count as ties.
* Symmetry breaking, tighter bounds for rest and likes, and a limit on the search stay in
  [Future work](../explanation/future-work.md#search-performance).
