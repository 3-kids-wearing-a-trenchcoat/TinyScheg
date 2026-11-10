# 0002. Backtracking search with forward checking

**Status:** Accepted. Amended by [0017](0017-plain-forward-checking-and-pruning-on-ties.md) (no automatic assignment of single-worker slots).

## Context

Constraint propagation alone (e.g. AC-3) removes impossible values from domains, but usually doesn't leave a clear
assignment. More values can only be ruled out by actually trying assignments and seeing their effects.

## Decision

Search with recursive **backtracking**: choose a slot, try a worker, propagate the effects, and either continue or
undo and try the next option.

After each assignment, propagate with **forward checking**: remove the assigned worker from the domain of every slot
that has a difference constraint with the assigned slot.

* If a domain becomes empty, the branch is unsatisfiable and the search backtracks immediately.
* If a domain is reduced to a single worker, that worker is assigned immediately, propagating further.

## Consequences

* Combinations that violate a constraint are never explored.
* Dead ends are detected as soon as a domain becomes empty, rather than when the dead-end slot is reached.
* Every assignment can cause a chain of further changes, all of which must be undone on backtracking
  (see [0008](0008-undo-through-trail.md)).
