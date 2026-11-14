# `problem` module: `Problem`

Source: [`src/tinyscheg/csp/problem.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/csp/problem.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_problem.py`).

The scheduling problem as a CSP (see [CSP formulation](../../explanation/csp-formulation.md)): slots are the
variables and workers the values. Workers and slots are referred to **by index**: a worker's index is its position in
the input, and a slot's index is its position in the stable slot order (`slot.index`).

## `class Problem(workers, shifts, slots, domains, neighbours, min_rest, interchangeable=(), fixed=(), settings=None, eligible=())`

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
* `fixed` — `tuple[int | None, ...]`: with a [history](../input-format.md#history), the worker of each history slot,
  and `None` for each new one; empty (the default) without a history. The search starts with the fixed slots filled.
* `settings` — the [`Settings`](schedule-input.md) of the whole schedule, whose period runs from the history's start
  to the new period's end; the input's own without a history. The scoring constants are built from it. `None` only
  for problems built by hand.
* `eligible` — `tuple[tuple[int, ...], ...]`: with a history, for each slot, the workers who could have filled it in
  a schedule made from scratch ([ADR 0037](../../decisions/0037-worst-rest-deficit-from-scratch-over-the-history.md)): for a history slot, everyone in that period's input who was available for
  its whole time and had its role then; for a new slot, its initial domain. Empty (the default) without a history.

Properties and methods:

* `is_fixed(slot_index)` — whether the slot is a history slot.
* `new_shifts`, `new_slots` — the new period's shifts and slots, the ones the search fills and the output shows:
  all of them without a history.
* `scoring_domains` — `eligible`, or `domains` without a history: what the scoring constants are built from, so
  that a worker's worst possible rest deficit doesn't depend on which history slots they were given.

## `build_problem(schedule_input) -> Problem`

Sets up the CSP for a validated `ScheduleInput`: generates its shifts and slots
([`generate_shifts`](post-and-slot.md#generate_shiftsposts-period-tupleshift)), then their domains and difference
constraints.

With a history, it sets up one schedule from the history's start to the new period's end, already filled up to the
new period ([ADR 0031](../../decisions/0031-history-as-the-filled-part-of-one-schedule.md)):

* the history's shifts come first, generated from each previous input (in order of their periods) with their
  workers, matched by name; slots of workers who have left are dropped, and so are shifts left with none;
* history slots have their worker as their only value, whatever the current rules, and aren't constrained with each
  other;
* each new slot's domain leaves out the workers of the history slots it's constrained with (overlap or minimum
  rest), as forward checking from them would;
* `workers` are the input's, each with the unavailability they had over the whole schedule: as in each history
  input during its period (all of it if they weren't in that input), as in this input during the new period, and
  all the time between periods, so that availability counts only the periods themselves;
* `eligible` holds who could have filled each slot from scratch, as above.

## `initial_domain(slot, workers) -> tuple[int, ...]`

Applies the unary constraints to a slot: the indexes of the workers who have the slot's role (`"any"` matches
everyone) and are available for its whole time range, ascending. Unavailability that only touches the slot's start
or end doesn't count, since ranges are half-open.

## `must_differ(first, second, min_rest) -> bool`

`True` if the two slots overlap, are back to back, or are less than `min_rest` apart, so one worker can't fill both.
A rest of exactly `min_rest` is allowed; back to back never is, even with a `min_rest` of 0
([ADR 0034](../../decisions/0034-never-back-to-back.md)).

## `difference_constraints(slots, min_rest) -> tuple[tuple[int, ...], ...]`

Finds every pair of slots that `must_differ`, as the `neighbours` of `Problem`.

* `slots` — all slots, in stable order (which is sorted by start time).
* `min_rest` — `datetime.timedelta`.

Each slot is compared with the slots after it, stopping at the first one that starts after this slot's end, by at
least `min_rest`: every slot after that starts later still, so none of them can be constrained with this one.

## `interchangeable_slots(slots) -> tuple[tuple[int, ...], ...]`

Finds each slot's interchangeable slots, as the `interchangeable` of `Problem`: the other slots of the same shift
with the same role.

## `unfillable_slots(problem) -> tuple[Slot, ...]`

The slots whose initial domain is empty, in stable order. If there are any, no legal schedule exists, and they're
reported without searching ([ADR 0020](../../decisions/0020-report-where-infeasibility-was-found.md)).
