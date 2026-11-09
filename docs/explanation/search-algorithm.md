# Search algorithm

TinyScheg looks for the **best** legal schedule, not just any legal one. It does this with a backtracking search
over the [CSP](csp-formulation.md), combined with branch and bound: a [penalty score](scoring.md) is kept for every
partial schedule, and branches that can't beat the best complete schedule found so far are pruned.

## Backtracking search

> [!WARNING]
> **Not yet implemented.** See [ADR 0002](../decisions/0002-backtracking-with-forward-checking.md).

The search is recursive, much like a depth-first search:

1. Choose the next variable (slot) to assign (see [Variable ordering](#variable-ordering)).
2. Try assigning it the next value (worker) from its domain.
3. Propagate the effects of the assignment with forward checking (see [Constraint propagation](#constraint-propagation)).
4. If some slot is left with an empty domain, undo the assignment and backtrack.
5. Otherwise, continue from step 1 with the new state.
6. Once every value of the current variable has been tried, return to the previous level.

Since TinyScheg doesn't stop at the first solution, every complete, legal schedule the search reaches is compared
against the pocket (see [Branch and bound](#branch-and-bound-the-pocket)).

## Constraint propagation

> [!IMPORTANT]
> **Partially implemented.** Propagation into a single slot (`Slot.propagate_constraint`) exists. `Slot.assign`,
> which should trigger propagation into every constrained slot, is a stub.

TinyScheg uses **forward checking**: after a worker is assigned to a slot, that worker is removed from the domain
of every slot that has a difference constraint with it. This avoids ever trying combinations that violate a
constraint.

* If a slot's domain becomes **empty**, the current partial schedule is unsatisfiable and the search backtracks.
* If a slot's domain is reduced to a **single** worker, that worker is assigned immediately, which in turn
  propagates further.
* Already-assigned slots are skipped.
* A global iteration counter (`Slot.iteration_ticker`) and a per-slot `last_iteration` mark which slots have
  already been checked during the current propagation round, so no slot is processed twice in one round.

## Variable ordering

> [!NOTE]
> **Implemented**, as `Slot.csp_lt`. See [ADR 0003](../decisions/0003-variable-ordering-mrv-degree.md).

The next slot to assign is chosen with two heuristics:

1. **Minimum Remaining Values (MRV)** — choose the slot with the smallest domain, i.e. the most constrained slot.
   This tends to surface dead ends early.
2. **Degree heuristic** (tie-breaker) — among slots with equally small domains, choose the one with the most
   constraints with still-unassigned slots (`Slot.unassigned_constraints`).

The intent is for a single comparison like this to let a self-balancing data structure keep slots ordered.

## Value ordering

> [!NOTE]
> **Decided.** No implementation is needed.

When looking for a single solution, a common heuristic is to try the **least constraining value** first. But when
the search explores all solutions rather than stopping at the first, the order in which values are tried doesn't
matter. TinyScheg searches for the best schedule, so workers are tried in no particular order, and `Worker` needs
no CSP-related ordering.

## Branch and bound: the pocket

> [!WARNING]
> **Not yet implemented.** See [ADR 0004](../decisions/0004-branch-and-bound-with-monotone-penalty.md).

Every schedule state, including incomplete ones, has a penalty score (see [Scoring](scoring.md)). The penalty never
decreases as more slots are assigned: each state's penalty is greater than or equal to its parent state's.

* When the search reaches a complete, legal schedule, it's saved together with its penalty "in a pocket".
* Each new complete, legal schedule is compared with the pocket schedule. If it's better, it replaces the pocket
  schedule; otherwise it's discarded.
* Once there's a pocket schedule, each partial schedule's penalty is compared with the pocket's. If the partial
  schedule is already worse, no schedule in its branch can be better (because penalty never decreases), so the
  whole branch is pruned.

When the search ends, the pocket holds the best schedule.

## Trail

> [!WARNING]
> **Not yet implemented.** See [ADR 0008](../decisions/0008-undo-through-trail.md).

Backtracking requires undoing an assignment *and everything it caused*: domain prunings, assignments made by
propagation, and score changes. The **`Trail`** is a stack that records these so they can be reverted exactly.

* Each item in the stack is a list of actions, always beginning with an assignment.
* A new item is pushed whenever a new assignment is reported; the actions that follow from it are added to that
  item.
* `Slot` and/or `Worker` report the actions they take through methods on the `Trail`.
* `undo` pops the top item and reverts every action in it.
* The trail may also need to keep track of which branch was chosen at each level (this may belong elsewhere).

## Schedule

> [!WARNING]
> **Not yet implemented.**

The planned `Schedule` class holds the list of slots, ordered according to the CSP heuristics, and the `Trail`, and
runs the search.
