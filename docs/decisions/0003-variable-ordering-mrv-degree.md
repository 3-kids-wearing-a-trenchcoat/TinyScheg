# 0003. Order variables by MRV and the degree heuristic; no value ordering

**Status:** Accepted

## Context

A backtracking search's efficiency depends heavily on the order in which variables are chosen. The order in which
values are tried matters too, but only when the search stops at the first solution found.

## Decision

* **Variable ordering:** choose the slot with the **minimum remaining values** (smallest domain) next. Break ties
  with the **degree heuristic**: the slot with the most constraints with unassigned slots.
  Both are expressed as a single comparison (`Slot.csp_lt`), so a self-balancing data structure can keep slots
  ordered.
* **Value ordering:** none. TinyScheg doesn't stop at the first solution, since it's looking for the best schedule
  (see [0004](0004-branch-and-bound-with-monotone-penalty.md)). When every solution is considered, the order in which
  values are tried doesn't matter, so heuristics like least-constraining-value don't apply.

## Consequences

* Each slot must keep track of how many of its constrained slots are still unassigned
  (`Slot.unassigned_constraints`), and that count must be updated on every assignment and undo.
* `Worker` needs no CSP-related ordering or comparison.
