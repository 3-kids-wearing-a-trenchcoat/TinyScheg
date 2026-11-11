# `state` and `search` modules

Sources: [`src/tinyscheg/csp/state.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/csp/state.py) and
[`src/tinyscheg/csp/search.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/csp/search.py)

See [Search algorithm](../../explanation/search-algorithm.md) for how the search works and why. As in
[`Problem`](problem.md), workers and slots are referred to by index.

## `state` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_state.py`).

The changing part of the search, and the change records used to undo assignments
([ADR 0016](../../decisions/0016-undo-through-change-records-on-the-call-stack.md)).

### `class SearchState(problem)`

The domains and assignments of all slots, starting from `problem.domains` with nothing assigned. The `Problem`
itself is never changed.

* `problem` — the `Problem`.
* `domains` — `list[tuple[int, ...]]`: for each slot, the workers who can still fill it, ascending. Domains are
  immutable tuples; changing one replaces it, so undo puts the saved tuple back rather than reversing an operation.
* `assigned` — `list[int | None]`: for each slot, the assigned worker, or `None`.

#### `assign(slot_index, worker) -> Changes`

Assigns `worker` to the unassigned slot `slot_index`, then **forward checks**: removes the worker from the domain of
every unassigned slot constrained with it. If a domain becomes empty, checking stops there, and `Changes.emptied`
says which slot it was.

**Raises** `ValueError` if the slot is already assigned, or the worker isn't in its domain.

#### `undo(changes) -> None`

Undoes an assignment, putting back the saved domains and clearing the assignment. Assignments must be undone in the
reverse order they were made, as the recursive search does.

### `class Changes(slot_index, saved_domains, emptied)`

Everything one `assign` changed. Immutable.

* `slot_index` — `int`, the slot that was assigned.
* `saved_domains` — `tuple[tuple[int, tuple[int, ...]], ...]`: (slot index, domain before the change) pairs, in the
  order the domains were changed.
* `emptied` — `int | None`, the slot whose domain became empty, if any.

## `search` module

> [!NOTE]
> **Implemented** for finding the first legal schedule, and covered by tests (`tests/test_search.py`).
> Branch and bound is [not yet implemented](../../explanation/search-algorithm.md).

### `find_first_schedule(problem) -> SearchResult`

Backtracking search with forward checking. Slots are chosen by `choose_slot` and workers tried in input order, so
the result is deterministic. Stops at the first complete, legal schedule.

### `choose_slot(state) -> int | None`

The next slot to fill, by [variable ordering](../../explanation/search-algorithm.md#variable-ordering)
([ADR 0003](../../decisions/0003-variable-ordering-mrv-degree.md)): the unassigned slot with the fewest workers
left in its domain; among those, the one constrained with the most unassigned slots; among those, the lowest index.
`None` if every slot is assigned. Computed by scanning the state each time; nothing is stored.

### `class SearchResult(assignment, deepest, stuck_slot)`

* `assignment` — `tuple[int, ...] | None`: a worker index per slot, or `None` if no legal schedule exists.
* `deepest` — `int`, the most slots the search had filled at once (all of them if it found a schedule).
* `stuck_slot` — `Slot | None`, the slot the search had to fill next at its deepest point; `None` if it found a
  schedule. Used to report where an infeasible input got stuck
  ([ADR 0020](../../decisions/0020-report-where-infeasibility-was-found.md)).

The stuck slot is where the search found out, not necessarily the cause: forward checking stops an assignment as soon
as it leaves some *other* slot with no workers, so the actual conflict may be a slot or two later. Since a slot with
an empty domain is always chosen next, a slot no worker can fill is reported before anything is filled.
