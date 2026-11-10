# 0016. Undo through change records on the call stack

**Status:** Accepted. Supersedes [0008](0008-undo-through-trail.md).

## Context

The depth-first search must undo every assignment, and everything it caused, when it backtracks.
[ADR 0008](0008-undo-through-trail.md) planned a `Trail`: a separate stack object to which `Slot` and `Worker`
report every action they take, and which undoes them by reverting those actions.

The underlying technique — recording changes and reverting them on backtrack, known as *trailing* — is the standard
one. But the planned design has drawbacks:

* Domain classes (`Slot`, `Worker`) would depend on search machinery, making dependencies flow both ways, and any
  change that isn't reported silently corrupts the search.
* Reverting *actions* (e.g. subtracting a score change that was added) isn't exact with floating-point arithmetic,
  which threatens determinism ([ADR 0012](0012-deterministic-path-independent-scoring.md)).
* Tracking which branch was chosen at each level duplicates what a recursive search already does.

Copying the whole state at each level was also considered. A depth-first search only holds the states along its
current path, so memory isn't a problem (roughly depth × state size, a few megabytes at the intended sizes), but
every step would cost a full copy.

## Decision

* The search is **recursive**. Each step records the changes it makes — the assignment itself and every worker
  removed from a domain by propagation — in a local change record, and undoes exactly those changes when it
  returns.
* Undo **restores saved values**; it never applies inverse operations. If incremental scoring is added later, the
  old values of any score terms it changes are saved in the same record.
* State that can be derived cheaply is **computed when needed rather than stored**: the number of unassigned
  constrained slots (degree heuristic), and the choice of the next slot (a scan for the smallest domain rather than a
  self-balancing ordered structure). There's no global iteration counter.
* The search state (domains and assignments) is an explicit object passed to the search, not class-level globals.

## Consequences

* Undo costs only as much as the changes being undone.
* Domain classes don't know about undo at all.
* Restoring saved values is exact, so undo never affects determinism.
* Python's default recursion limit (1000) is far above the search depth (one level per slot, about 100 at the
  intended sizes).
