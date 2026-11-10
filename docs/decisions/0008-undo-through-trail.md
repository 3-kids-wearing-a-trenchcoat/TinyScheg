# 0008. Undo assignments through a trail

**Status:** Superseded by [0016](0016-undo-through-change-records-on-the-call-stack.md).

## Context

When the search backtracks, it must revert an assignment and everything that followed from it: domain prunings,
further assignments made by propagation, and changes to scores and counters.

## Decision

Record every change in a **`Trail`**: a stack in which each item is the list of actions caused by one assignment,
beginning with the assignment itself. `Slot` and `Worker` report the actions they take to the trail. Undoing pops
the top item and reverts its actions.

## Consequences

* Every operation that changes search state must be reported to the trail, and must be reversible.
* Score changes can be reverted exactly, without recalculating scores from scratch.
