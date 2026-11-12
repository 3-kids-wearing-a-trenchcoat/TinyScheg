# `problem` module: `Problem`

Source: [`src/tinyscheg/csp/problem.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/csp/problem.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_problem.py`).

The scheduling problem as a CSP (see [CSP formulation](../../explanation/csp-formulation.md)): slots are the
variables and workers the values. Workers and slots are referred to **by index**: a worker's index is its position in
the input, and a slot's index is its position in the stable slot order (`slot.index`).

## `class Problem(workers, shifts, slots, domains, neighbours, min_rest, interchangeable=())`

The fixed description of a scheduling CSP. It's immutable and doesn't change during the search, which keeps its own
state, starting from `domains`.

* `workers` — `tuple[Worker, ...]`, in input order.
* `shifts` — `tuple[Shift, ...]`, in stable order.
* `slots` — `tuple[Slot, ...]`, in stable order; `slots[i].index == i`.
* `domains` — `tuple[tuple[int, ...], ...]`: for each slot, the indexes of the workers who can fill it, ascending.
  Ascending worker index is input order, which is the order workers are tried in
  (see [Search algorithm](../../explanation/search-algorithm.md#value-ordering)).
* `neighbours` — `tuple[tuple[int, ...], ...]`: for each slot, the indexes of the slots that must get a different
  worker, ascending. Constraints are symmetric, and a slot is never its own neighbour.
* `min_rest` — `datetime.timedelta`, the minimum rest between two of a worker's shifts.
* `interchangeable` — `tuple[tuple[int, ...], ...]`: for each slot, the indexes of the other slots of its shift that
  need the same role, ascending; the search fills them in ascending worker order
  ([ADR 0025](../../decisions/0025-order-interchangeable-slots.md)). Empty (the default) for none.

## `build_problem(schedule_input) -> Problem`

Sets up the CSP for a validated `ScheduleInput`: generates its shifts and slots
([`generate_shifts`](post-and-slot.md#generate_shiftsposts-period-tupleshift)), then their domains and difference
constraints.

## `initial_domain(slot, workers) -> tuple[int, ...]`

Applies the unary constraints to a slot: the indexes of the workers who have the slot's role (`"any"` matches
everyone) and are available for its whole time range, ascending. Unavailability that only touches the slot's start
or end doesn't count, since ranges are half-open.

## `must_differ(first, second, min_rest) -> bool`

`True` if the two slots overlap, or are less than `min_rest` apart, so one worker can't fill both. A rest of exactly
`min_rest` is allowed.

## `difference_constraints(slots, min_rest) -> tuple[tuple[int, ...], ...]`

Finds every pair of slots that `must_differ`, as the `neighbours` of `Problem`.

* `slots` — all slots, in stable order (which is sorted by start time).
* `min_rest` — `datetime.timedelta`.

Each slot is compared with the slots after it, stopping at the first one that starts at or after this slot's end plus
`min_rest`: every slot after that starts later still, so none of them can be constrained with this one.

## `interchangeable_slots(slots) -> tuple[tuple[int, ...], ...]`

Finds each slot's interchangeable slots, as the `interchangeable` of `Problem`: the other slots of the same shift
with the same role.

## `unfillable_slots(problem) -> tuple[Slot, ...]`

The slots whose initial domain is empty, in stable order. If there are any, no legal schedule exists, and they're
reported without searching ([ADR 0020](../../decisions/0020-report-where-infeasibility-was-found.md)).
