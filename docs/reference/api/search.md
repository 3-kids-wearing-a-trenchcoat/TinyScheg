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
every unassigned slot constrained with it, and keeps the slot's unassigned interchangeable slots in ascending worker
order: later ones keep only the workers after `worker`, earlier ones only those before it
([ADR 0025](../../decisions/0025-order-interchangeable-slots.md)). If a domain becomes empty, checking stops there,
and `Changes.emptied` says which slot it was.

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
> **Implemented**, and covered by tests (`tests/test_search.py`). The command line uses `find_best_schedule`.

### `find_first_schedule(problem) -> SearchResult`

Backtracking search with forward checking. Slots are chosen by `choose_slot` and workers tried in input order, so
the result is deterministic. Stops at the first complete, legal schedule.

### `find_best_schedule(problem, constants, prune=True, on_improvement=None, incremental=True) -> SearchResult`

[Branch and bound](../../explanation/search-algorithm.md#branch-and-bound-the-pocket): the same search, run to the
end, keeping the best complete schedule found so far in the pocket. At every partial schedule a
[lower bound](scoring.md#lower_boundconstants-assignment-domains-float) on the penalty of its completions
is compared with the pocket's penalty; if it's at least as high, the branch is pruned, since ties keep the pocket
([ADR 0017](../../decisions/0017-plain-forward-checking-and-pruning-on-ties.md)). A slot's workers are tried
cheapest first: by the penalty with them assigned, ties in input order
([ADR 0024](../../decisions/0024-cheapest-first-value-order-and-workload-bound.md)). Both are kept by an
[`IncrementalScore`](scoring.md#incremental-module); a bound within `NEAR_TIE_MARGIN` (1e-9) of the pocket's penalty
is computed from scratch, and so is every complete schedule's penalty
([ADR 0027](../../decisions/0027-incremental-scoring-for-steering.md)).

* `constants` — the [`ScoringConstants`](scoring.md#class-scoringconstants) of the same input.
* `prune` — `False` only for testing: every branch is searched, to check that pruning loses nothing.
* `incremental` — `False` only for testing and comparing: the search steers by scoring from scratch, as before
  ADR 0027. The result is the same either way.
* `on_improvement` — `Callable[[Penalty], None] | None`: called with the penalty of each better schedule as it's
  put in the pocket, e.g. to show progress.

The search always runs to the end, however long that takes.

Returns the legal schedule with the lowest penalty; of equally good schedules, the first found, so the result is
deterministic. If there's none, it reports where the search got stuck, as `find_first_schedule` does.

### `choose_slot(state) -> int | None`

The next slot to fill, by [variable ordering](../../explanation/search-algorithm.md#variable-ordering)
([ADR 0003](../../decisions/0003-variable-ordering-mrv-degree.md)): the unassigned slot with the fewest workers
left in its domain; among those, the one constrained with the most unassigned slots; among those, the lowest index.
`None` if every slot is assigned. Computed by scanning the state each time; nothing is stored.

### `class SearchResult(assignment, deepest, stuck_slot, penalty=None, nodes=0, pruned=0)`

* `assignment` — `tuple[int, ...] | None`: a worker index per slot, or `None` if no legal schedule exists.
* `deepest` — `int`, the most slots the search had filled at once (all of them if it found a schedule).
* `stuck_slot` — `Slot | None`, the slot the search had to fill next at its deepest point; `None` if it found a
  schedule. Used to report where an infeasible input got stuck
  ([ADR 0020](../../decisions/0020-report-where-infeasibility-was-found.md)).
* `penalty` — `Penalty | None`, the schedule's penalty, from `find_best_schedule`; `None` from
  `find_first_schedule`, or if no legal schedule exists.
* `nodes` — `int`, how many (partial) schedules the search visited.
* `pruned` — `int`, how many branches branch and bound cut off because they couldn't beat the pocket.

The stuck slot is where the search found out, not necessarily the cause: forward checking stops an assignment as soon
as it leaves some *other* slot with no workers, so the actual conflict may be a slot or two later. Since a slot with
an empty domain is always chosen next, a slot no worker can fill is reported before anything is filled.
