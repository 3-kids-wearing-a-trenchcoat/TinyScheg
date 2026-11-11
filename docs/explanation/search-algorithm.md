# Search algorithm

TinyScheg looks for the **best** legal schedule, not just any legal one. It does this with a backtracking search
over the [CSP](csp-formulation.md), combined with branch and bound: a [penalty score](scoring.md) is kept for every
partial schedule, and branches that can't beat the best complete schedule found so far are pruned.

> [!IMPORTANT]
> **Partially implemented.** Everything on this page is implemented in [`csp/search.py`](../reference/api/search.md)
> and tested, but the command line still writes the **first** legal schedule: branch and bound is only checked on
> small inputs so far, and its speed on realistic inputs is still to be measured (see the
> [Roadmap](../roadmap.md#phase-5-branch-and-bound)).

## Overview

```
search(state):
    penalty = score(state)                      # from scratch; never decreases as slots are assigned
    if pocket exists and penalty >= pocket.penalty:
        return                                  # prune: this branch can't beat the pocket
    if every slot is assigned:
        pocket = copy of state, with its penalty
        return
    slot = next slot to assign                  # MRV, then degree, then stable slot order
    for worker in slot's domain, in stable (input) order:
        changes = assign worker to slot, then forward check
        if no domain became empty:
            search(state)
        undo(changes)                           # restore exactly what was changed
```

When the search ends, the pocket holds the best schedule. If it's empty, no legal schedule exists: TinyScheg
reports that and produces no output ([ADR 0011](../decisions/0011-no-output-for-infeasible-inputs.md)), naming the
deepest point the search reached and the slot it couldn't fill there
([ADR 0020](../decisions/0020-report-where-infeasibility-was-found.md)).

## Backtracking search

> [!NOTE]
> **Implemented**, both for the best schedule (all steps) and for the first legal one (steps 2–5, stopping at the
> first complete schedule).

The search is recursive, much like a depth-first search
([ADR 0002](../decisions/0002-backtracking-with-forward-checking.md)):

1. Score the current state, and prune it if it can't beat the pocket (see
   [Branch and bound](#branch-and-bound-the-pocket)).
2. If every slot is assigned, the state is a complete, legal schedule; compare it with the pocket.
3. Otherwise, choose the next slot to assign (see [Variable ordering](#variable-ordering)).
4. Try each worker in its domain in turn: assign it and propagate the effects (see
   [Constraint propagation](#constraint-propagation)). If no domain became empty, continue from step 1 with the
   new state.
5. Undo the assignment and its effects before trying the next worker (see [Undo](#undo)).

## Constraint propagation

> [!NOTE]
> **Implemented.** See [`SearchState.assign`](../reference/api/search.md#assignslot_index-worker-changes).

TinyScheg uses plain **forward checking** ([ADR 0017](../decisions/0017-plain-forward-checking-and-pruning-on-ties.md)):
after a worker is assigned to a slot, that worker is removed from the domain of every unassigned slot that has a
difference constraint with it. This avoids ever trying combinations that violate a constraint.

* If a slot's domain becomes **empty**, the current partial schedule is unsatisfiable and the search backtracks.
* A slot whose domain is reduced to a **single** worker is not assigned automatically: having the smallest possible
  domain, it's the next slot chosen anyway.

## Variable ordering

> [!NOTE]
> **Implemented.** See [`choose_slot`](../reference/api/search.md#choose_slotstate-int-none).

See [ADR 0003](../decisions/0003-variable-ordering-mrv-degree.md) and
[ADR 0017](../decisions/0017-plain-forward-checking-and-pruning-on-ties.md).

The next slot to assign is chosen among the unassigned slots by:

1. **Minimum Remaining Values (MRV)** — the slot with the smallest domain, i.e. the most constrained slot. This tends
   to surface dead ends early.
2. **Degree heuristic** (first tie-breaker) — among those, the slot with the most constraints with still-unassigned
   slots.
3. **Stable slot order** (final tie-breaker) — the slot that comes first in the fixed slot order (see
   [Domain model](domain-model.md#shifts-and-slots)), so the choice is always deterministic
   ([ADR 0012](../decisions/0012-deterministic-path-independent-scoring.md)).

Both the domain sizes and the number of unassigned neighbours are computed when the choice is made, by scanning the
unassigned slots, rather than kept in a sorted structure. At the intended schedule sizes (around a hundred slots),
this is cheap. The number of unassigned neighbours is only counted for the slots tied on domain size.

The difference this makes is large. On an infeasible input of seven workers and 47 slots, filling slots in stable
order hadn't established that no schedule exists after several minutes; MRV does it at once, since it fills the
night shifts that few workers can still take before they run out. A side effect is that the slot an infeasible
input is reported stuck at ([ADR 0020](../decisions/0020-report-where-infeasibility-was-found.md)) tends to be the
real bottleneck: a slot with no workers left is always chosen next, so the search reports it before filling
anything else.

## Value ordering

> [!NOTE]
> **Decided.** No implementation is needed beyond trying workers in input order.

When looking for a single solution, a common heuristic is to try the **least constraining value** first. But when
the search explores all solutions rather than stopping at the first, the order in which values are tried doesn't
change the result. TinyScheg searches for the best schedule, so workers are tried in a fixed, stable order (their
order in the input), and `Worker` needs no CSP-related ordering.

Value order can still affect how *quickly* branch and bound finds the best schedule; see
[Future work](future-work.md#search-performance).

## Branch and bound: the pocket

> [!NOTE]
> **Implemented**, in [`find_best_schedule`](../reference/api/search.md#find_best_scheduleproblem-constants-prunetrue-searchresult),
> and tested against trying every schedule on small inputs. Not yet used by the command line.

See [ADR 0004](../decisions/0004-branch-and-bound-with-monotone-penalty.md) and
[ADR 0017](../decisions/0017-plain-forward-checking-and-pruning-on-ties.md).

Every schedule state, including incomplete ones, has a penalty score (see [Scoring](scoring.md)). The penalty never
decreases as more slots are assigned: each state's penalty is greater than or equal to its parent state's.

* When the search reaches a complete, legal schedule, it's saved together with its penalty "in a pocket".
* Each new complete, legal schedule is compared with the pocket schedule. If its penalty is lower, it replaces the
  pocket schedule; otherwise it's discarded. On equal penalties, the schedule found first stays.
* Once there's a pocket schedule, each partial schedule's penalty is compared with the pocket's. If it's already
  **greater than or equal to** the pocket's, no schedule in its branch can replace the pocket (because penalty never
  decreases, and ties keep the pocket), so the whole branch is pruned.

When the search ends, the pocket holds the best schedule.

## Undo

> [!NOTE]
> **Implemented.** See [`Changes` and `SearchState.undo`](../reference/api/search.md#state-module).

See [ADR 0016](../decisions/0016-undo-through-change-records-on-the-call-stack.md).

Backtracking requires undoing an assignment *and everything it caused*. Each step of the search records the changes
it makes — the assignment itself, and every worker removed from a domain by forward checking — and undoes exactly
those changes before trying its next worker.

* Undo **restores saved values**; it never applies inverse operations, so it's exact and can't affect
  [determinism](../decisions/0012-deterministic-path-independent-scoring.md).
* The change records live with the search (on the call stack of the recursive search); `Slot` and `Worker` don't
  know about undo.
* The loop over a slot's domain is itself the record of which branch is being explored, so nothing else is needed.

## Search state

> [!NOTE]
> **Implemented.** See [`SearchState`](../reference/api/search.md#class-searchstateproblem).

The search operates on an explicit state object — the domains and assignments of all slots — that is passed to the
search, rather than on class-level globals.
