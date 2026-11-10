# Glossary

**Assignment** — Placing a worker in a slot. A schedule state is the set of assignments made so far.

**Constraint propagation** — Using constraints to shrink slot domains after an assignment. TinyScheg uses forward
checking. See [Search algorithm](search-algorithm.md#constraint-propagation).

**Difference constraint** (diff constraint) — A binary constraint between two slots that must be assigned
different workers, because they overlap in time or are less than the minimum rest period apart.
See [CSP formulation](csp-formulation.md#binary-difference-constraints).

**Dangling shift** — A shift cut short at the end of its segment, because the segment's length isn't a multiple of
the shift length.

**Domain** — The set of workers who can still be assigned to a slot.

**Minimum rest period** — The least amount of time, in hours, that must separate two shifts assigned to the same
worker. A hard constraint, set in the input (`min_rest`) and defaulting to 6 hours.

**MRV (Minimum Remaining Values)** — The heuristic of assigning the slot with the smallest domain next. Ties are
broken by the **degree heuristic**: the slot with the most constraints with unassigned slots.
See [Search algorithm](search-algorithm.md#variable-ordering).

**Penalty** — The score of a schedule state: lower is better, and it never decreases as more slots are assigned.
See [Scoring](scoring.md).

**Pocket** — The best complete, legal schedule found so far during the search, kept for comparison with other
schedules and for pruning. See [Search algorithm](search-algorithm.md#branch-and-bound-the-pocket).

**Post** — Something that needs to be manned (e.g. "front gate"). A template from which shifts and slots are
generated. See [Domain model](domain-model.md#posts).

**Role** — A qualification a worker has and a slot may require. The role `any` is a wildcard that every worker
has.

**Scorer** — A per-worker object holding what's needed to calculate that worker's penalty. Not yet implemented.

**Segment** — A stretch of the schedule period during which a post's rules (shift length, roles) don't change.
Shifts are generated per segment. See [Domain model](domain-model.md#shifts-and-slots).

**Shift** — A post during one specific time range; a group of slots that are manned together.
See [Domain model](domain-model.md#shifts-and-slots).

**Slot** — A single position, for a single worker with a given role, during one shift. Slots are the CSP's
variables. See [Domain model](domain-model.md#shifts-and-slots).

**Undo** — Reverting an assignment and everything it caused when the search backtracks, by restoring the values
recorded when the changes were made. See [Search algorithm](search-algorithm.md#undo).

**Unavailability** — A date-time range during which a worker can't be assigned. Workers are available at all other
times.

**Variation** — A recurring daily time window during which a post's requirements (roles, shift length) differ from
its general case. See [Domain model](domain-model.md#variations).

**Worker** — Someone who can be assigned to slots. See [Domain model](domain-model.md#workers).
