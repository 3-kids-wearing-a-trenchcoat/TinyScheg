# Search algorithm

TinyScheg looks for the **best** legal schedule, not just any legal one. It does this with a backtracking search
over the [CSP](csp-formulation.md), combined with branch and bound: a [penalty score](scoring.md) is kept for every
partial schedule, and branches that can't beat the best complete schedule found so far are pruned.

> [!NOTE]
> **Implemented** in [`csp/search.py`](../reference/api/search.md), tested, and used by the command line. The search
> always runs to the end, with no limit, in [parallel processes](#parallel-search) by default: about 2 seconds for
> the 24-hour example (20 in one process), while a 48-hour schedule can take much longer (about 12 minutes for the
> example stretched to 48 hours, in parallel on PyPy). It shows
> its [progress](#progress) as it goes, and can be stopped with Ctrl+C, keeping the best schedule found so far.
> Making it faster is [future work](future-work.md#search-performance).

## Overview

```
search(state):
    if pocket exists and lower_bound(state) >= pocket.penalty:
        return                                  # prune: no completion of this branch can beat the pocket
    if every slot is assigned:
        if penalty(state) < pocket.penalty:     # scored from scratch; on a tie, the pocket stays
            pocket = copy of state, with its penalty
        return
    slot = next slot to assign                  # MRV, then degree, then stable slot order
    for worker in slot's domain, cheapest first:  # by the penalty with them assigned, ties in input order
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

1. Compute a lower bound on the penalty of every completion of the current state, and prune it if it can't beat
   the pocket (see [Branch and bound](#branch-and-bound-the-pocket)).
2. If every slot is assigned, the state is a complete, legal schedule; compare it with the pocket.
3. Otherwise, choose the next slot to assign (see [Variable ordering](#variable-ordering)).
4. Try each worker in its domain in turn (cheapest first, see [Value ordering](#value-ordering)): assign it and
   propagate the effects (see
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

Forward checking also removes **symmetric duplicates** ([ADR 0025](../decisions/0025-order-interchangeable-slots.md)):
slots of the same shift that need the same role are interchangeable, so they're filled in ascending worker order.
When one is assigned, the later ones keep only the workers after it, and the earlier ones only those before it. Every
schedule has an equivalent in this order, with the same penalty, so nothing is lost. Shifts themselves are never
treated as interchangeable: in asymmetric schedules they differ in length, rest targets and availability.

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
> **Implemented.** See [ADR 0024](../decisions/0024-cheapest-first-value-order-and-workload-bound.md).

When looking for a single solution, a common heuristic is to try the **least constraining value** first. But when
the search explores all solutions rather than stopping at the first, the order in which values are tried doesn't
change the result, so that heuristic doesn't apply, and `Worker` needs no CSP-related ordering.

Value order still affects how *quickly* branch and bound finds and proves the best schedule: the sooner the pocket
holds a good schedule, the more branches can be pruned. So when looking for the best schedule, a slot's workers are
tried **cheapest first**: in order of the penalty of the schedule with them assigned, ties in input order. The best
penalty found is the same either way; of several equally good schedules, the first found in this order is kept, so
the result stays deterministic. When looking for the first legal schedule, workers are tried in input order.

## Branch and bound: the pocket

> [!NOTE]
> **Implemented**, in [`find_best_schedule`](../reference/api/search.md#find_best_scheduleproblem-constants-prunetrue-on_improvementnone-incrementaltrue-on_progressnone-keep_best_on_interruptfalse-searchresult),
> and tested against trying every schedule on small inputs, and on shortened versions of the example, where no single
> legal move or swap of two workers beats the schedule it finds.

See [ADR 0004](../decisions/0004-branch-and-bound-with-monotone-penalty.md) and
[ADR 0017](../decisions/0017-plain-forward-checking-and-pruning-on-ties.md).

Every schedule state, including incomplete ones, has a penalty score (see [Scoring](scoring.md)). The penalty never
decreases as more slots are assigned: each state's penalty is greater than or equal to its parent state's.

* When the search reaches a complete, legal schedule, it's saved together with its penalty "in a pocket".
* Each new complete, legal schedule is compared with the pocket schedule. If its penalty is lower, it replaces the
  pocket schedule; otherwise it's discarded. On equal penalties, the schedule found first stays.
* Once there's a pocket schedule, each partial schedule is compared with the pocket. If no schedule in its branch
  can have a lower penalty than the pocket's, the whole branch is pruned; ties keep the pocket, so a branch that can
  at best tie is pruned too.

What's compared is a **lower bound** on the penalty of every schedule in the branch
([ADR 0024](../decisions/0024-cheapest-first-value-order-and-workload-bound.md)). The penalty so far would do, since
it never decreases, but it's weak: the workload penalty barely grows until the last slots are filled, and the likes
penalty counts only the pairs already filled. So the bound looks ahead, using the current domains:

* **Workload:** every unfilled slot's load must go to a worker in its domain. The bound is the higher of two
  estimates:
  * **Water-filling:** each worker's workload term is convex, so the total is lowest when the load tops up the
    least-loaded workers to a common level of load per available hour, like water filling vessels. Each worker rises
    only up to the load of the unfilled slots they could take, like vessels of different heights.
  * **Whole slots** ([ADR 0040](../decisions/0040-workload-bound-in-whole-slots.md)): in a real schedule each slot
    goes whole to one worker, which water-filling ignores. That's where almost all of its slack was, and the workload
    weight multiplies it. Each worker's lowest cost is found on its own, over the whole numbers of the remaining slots
    they could take, with a price on each unit of load (Lagrangian relaxation) set so that, in all, about the
    remaining load is handed out. Any price gives a valid bound, so the bound is never above a completion.
  * The whole-slot estimate costs most of the search's time, so the search first checks the bound with water-filling
    alone: where that already reaches the pocket, the full bound would too, and the whole-slot estimate is skipped
    (the same decisions, about 1.8 times faster on CPython, 2026-11-15).
* **Likes:** each pair of slots in a shared shift will add both workers' like values of each other; a pair with an
  unfilled slot adds at least the lowest value the workers still in its domains could give.
* **Rest:** the penalty so far. A worker can always be given no further shifts, so no future deficit is certain.

Both look-aheads relax the problem (ignoring which slots overlap, and choosing each pair's best independently), so
the bound may be lower than anything reachable, but never higher. A tighter bound only prunes branches that can't
beat the pocket, so it changes how fast the search finishes, never which schedule it finds. Neither look-ahead
assumes anything about shift lengths: in asymmetric schedules, with shifts of different lengths, dangling shifts or
variations, it holds all the same, and the brute-force tests include such inputs.

### Incremental scoring

> [!NOTE]
> **Implemented**, and covered by tests. See [ADR 0027](../decisions/0027-incremental-scoring-for-steering.md).

The value order and the bound are kept **incrementally**: running totals updated by what each assignment changes
(one worker's load and rest, one shift's pairings, the domains narrowed by forward checking), and restored exactly on
backtracking. They only **steer** the search. What decides its result is scored from scratch: a bound within a tiny
margin of the pocket's penalty (a near-tie), and every complete schedule before it's compared with the pocket. So the
search makes exactly the same decisions as with scoring from scratch, and finds the same penalty; on the example and
the benchmark inputs, it visits the same nodes and finds the same schedules, about 1.7 times faster (2026-11-12).

When the search ends, the pocket holds the best schedule.

### Parallel search

> [!NOTE]
> **Implemented**, and covered by tests. See
> [ADR 0041](../decisions/0041-parallel-search-with-the-sequential-result.md).

Python runs one thread at a time, so the search runs in several **processes**, by default one per processor, with
little shared between them. Most of a search's time goes into proving that nothing beats the best schedule, found
early, and that work can be shared out without waste.

* **Cutting the tree.** The tree is cut, at the first depth giving at least 32 subtrees per process, into subtrees
  numbered in the order the one-process search would visit them. Each subtree is reached by replaying its path's
  assignments in the same order, so everything below it, including the order workers are tried in, is exactly what
  the one-process search would do there.
* **Sharing the best.** The processes take subtrees from a queue, in order, and share the best schedule found so far,
  with the number of the subtree it came from. Each prunes on it, so a good schedule found by one prunes them all.
* **Ties.** Of equally good schedules, the one-process search keeps the first found. To keep the same one, a subtree
  coming before the best's may still produce a schedule with the same penalty, and it replaces the best; later ones
  can't. In the end, each subtree's best is merged by penalty, then by subtree.

So the schedule found is the same as in one process, whatever the timing; only the node counts differ from run to
run. On the example and the benchmark inputs, 8 processes ran about 7.6 times faster than one, with as many nodes in
all (on 8 cores; more processes than cores add little). The progress, the best schedules found and Ctrl+C work as in
one process; the main process gathers them from the others.

## Progress

> [!NOTE]
> **Implemented**, and covered by tests. See
> [ADR 0035](../decisions/0035-search-progress-and-keeping-the-best-on-interrupt.md).

Since the search runs as long as it needs, it reports how far it has got: the **share of the search space
finished**. The root counts as 1, and each partial schedule's share is split equally among the workers tried for its
next slot. When a branch is finished (searched to the end, pruned because it can't beat the pocket, or a dead end),
its share is added to a running total. The total only rises, and reaches 1 exactly when the search ends.

The time left is estimated from it, as the time elapsed times the share left over the share finished. That's rough,
and labelled so: branches are tried cheapest first, so the early ones, where the good schedules are, take longest,
while later ones are mostly pruned at once; the estimate starts high and improves as the run goes on. The share
also advances unevenly, jumping when a large branch is pruned.

The tracking only observes the search: which branches are searched, the schedule found and the node counts are
exactly the same with or without it (checked on the example and the benchmark inputs), and it costs one addition per
node. Ctrl+C stops the search and returns the best schedule found so far, marked as not proven the best; the
[command line](../reference/command-line.md#stopping-early-ctrlc) writes it.

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
