# 0027. Incremental scoring to steer the search, exact scoring to decide it

**Status:** Proposed.

## Context

At every node, branch and bound computes everything from scratch, as
[ADR 0012](0012-deterministic-path-independent-scoring.md) requires until incremental scoring is introduced: a full
penalty for each candidate worker of the chosen slot, for the cheapest-first order
([ADR 0024](0024-cheapest-first-value-order-and-workload-bound.md)), and a full lower bound for pruning. Profiling on
2026-11-12 showed about 90% of the search's time going to this, though one assignment changes very little: one
worker gains one slot, one shift gains one member, and forward checking narrows a few nearby domains. The cost of
recomputing grows with the size of the schedule, while what an assignment changes doesn't, so longer schedules
suffer most.

ADR 0012 allows incremental scoring only if it's exactly path-independent, for example with exact arithmetic. That
would be slow, and awkward with weights and parameters that are real numbers from the input. But not every value
the search computes decides its result:

* The **value order** only steers which branch is searched first. Every branch is still searched or pruned.
* The **lower bound** decides pruning, which can change the result only when the bound is about equal to the
  pocket's penalty.
* The **penalty of a complete schedule** decides what goes in the pocket, and so the result.

Complete schedules are rare: measured on 2026-11-12, the search reaches only 6 to 16 per run, against tens of
thousands of nodes, since a branch that can at best tie the pocket is pruned
([ADR 0017](0017-plain-forward-checking-and-pruning-on-ties.md)).

## Decision

**Incremental values steer the search; exact, from-scratch values decide it.**

1. **Running totals.** A scoring state keeps the totals the penalty and the lower bound are made of (likes over the
   filled pairs, each worker's load and rest deficit, each shift's share of the likes look-ahead, each worker's
   workload cap), updates them by what each assignment changes, and is rolled back on backtracking by **restoring
   the saved values**, never by subtracting, so that undoing is exact. The totals may still depend, by rounding, on
   the order in which slots were filled.
2. **The value order** uses the incremental cost of each candidate worker.
3. **Pruning** compares the incremental bound $\tilde{b}$ with the pocket's penalty $P$, with a margin $\varepsilon$
   (a named constant, far above any rounding difference and far below any difference that matters):
   * $\tilde{b} \geq P + \varepsilon$: prune.
   * $\tilde{b} \leq P - \varepsilon$: don't prune.
   * In between, a **near-tie**: the bound is computed from scratch, and the branch is pruned if it's at least $P$,
     exactly as now. So pruning decides exactly as from-scratch scoring would, ties included.
4. **Complete schedules** are scored from scratch before being compared with the pocket, and the pocket keeps the
   exact penalty. The pocket keeps the schedule found first among equal penalties, as ADR 0012 requires.
5. **The from-scratch functions stay**, as the definition of the penalty and as the test oracle: in tests, every node
   compares the incremental totals and bound with the from-scratch ones.

This amends ADR 0012: path independence is required of every value that **decides** the result (a complete
schedule's penalty, the pocket, and pruning near a tie), not of values that only steer the search.

Rejected:

* **Exact arithmetic** (fractions or scaled integers) throughout: exactly path-independent, but much slower, and
  complicated by real-number weights and parameters.
* **Incremental values everywhere, with no exact checks:** rounding differences of about $10^{-13}$ couldn't matter
  to fairness, but a later schedule tied with the pocket could look a rounding error better and replace it,
  making which tied schedule is kept depend on rounding; the reported penalty would differ, in its last digits, from
  that of the written schedule; and the brute-force tests would need a tolerance. Scoring the few complete schedules
  exactly costs nothing measurable.
* **A plain safety margin** (prune only if $\tilde{b} - \varepsilon \geq P$): it never loses a better schedule, but
  it stops pruning exact ties, which are common (workers who could swap without any difference), and so would search
  far more.

## Consequences

* The best penalty, and the pruning decisions, are exactly those of from-scratch scoring, as long as rounding stays
  below $\varepsilon$; tests check that it does.
* The value order among candidates whose costs differ only by rounding may differ from from-scratch scoring, so which
  of several equally good schedules is written can differ from earlier versions, as with ADRs 0024 and 0025. The
  result stays deterministic: the same input always gives the same schedule.
* Each formula has two implementations, from scratch and incremental, and a change to the scoring has to be made in
  both; the node-by-node tests catch any mismatch.
* The incremental state belongs to the `scoring` package, which keeps it independent of the search: the search
  passes it what changed (the slot assigned, and the domains narrowed) as plain data.
* Faster search, by an amount to be measured. Most of the work per node becomes proportional to what an assignment
  changes rather than to the size of the schedule; the water level of the workload bound is still recomputed at
  every node, but that's one pass over the workers.
