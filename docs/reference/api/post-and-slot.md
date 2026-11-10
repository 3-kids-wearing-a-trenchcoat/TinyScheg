# `post` and `shift` modules: `Post` and `Slot`

Sources: [`src/tinyscheg/model/post.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/post.py) and
[`src/tinyscheg/model/shift.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/shift.py)

See [Domain model](../../explanation/domain-model.md) for how posts, shifts and slots relate to each other.

## `post` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_post.py`). Generating shifts from posts is
> [not yet implemented](../../explanation/domain-model.md#shifts-and-slots).

Posts are immutable, hashable descriptions. Converting the input's time windows and filling in the fields a variation
inherits from its post is done by [input parsing](parsing.md).

### `class ShiftRules(length, roles)`

What each shift needs.

* `length` — `datetime.timedelta`, the shift length. Must be positive.
* `roles` — `tuple[tuple[str, int], ...]`, pairs of a role and the number of workers of that role each shift needs,
  in input order (which is part of the stable slot order). Role names must not repeat, and counts are whole numbers
  of at least 0. No roles at all (`()`) is allowed: such shifts need no workers.

`workers_needed` (property) is the total number of workers each shift needs.

**Raises** `ValueError` if any of the above doesn't hold.

### `class Variation(window, rules)`

A [`DailyWindow`](daily-window.md) during which a post's shifts follow different `ShiftRules`. Always fully
specified: fields the input leaves out are already filled in from the post.

### `class Post(name, rules, window=None, variations=())`

Something that needs to be manned, as a template for its shifts.

* `name` — `str`, the post name. Names are unique (checked by [validation](parsing.md#validateschedule_input)).
* `rules` — `ShiftRules`, the general case.
* `window` — `DailyWindow | None`, the daily window during which the post is active; `None` means always active.
* `variations` — the post's `Variation`s, stored as a `tuple`. They must not overlap one another (checked by
  validation).

## `shift` module

> [!IMPORTANT]
> This part documents the code as it currently stands, which is due to be rebuilt. Parts of it follow an earlier
> design that has since been revised:
> * Shifts are now to be generated per segment ([ADR 0018](../../decisions/0018-slot-generation-by-segments.md)),
>   in a new `model/shift_generation.py`. The old `Post.gen_slot_list` and `Post.get_variation` were removed with the
>   old `Post`.
> * `propagate_constraint` assigns single-worker slots automatically and uses a global iteration counter; propagation
>   is now plain forward checking ([ADR 0017](../../decisions/0017-plain-forward-checking-and-pruning-on-ties.md)).
> * `Slot.worker_list`, `Slot.iteration_ticker`, `last_iteration` and `unassigned_constraints`, and reporting to a
>   `Trail`, are replaced by an explicit search state and change records
>   ([ADR 0016](../../decisions/0016-undo-through-change-records-on-the-call-stack.md)).
> * `Slot` is to become a plain, unchanging description of a slot (time, post, role, shift), with a `Shift` grouping
>   the slots of each shift in place of `same_shift`. Domains, constraints and assignments move to the CSP setup and
>   search state (`csp/`) (see [Architecture](../../explanation/architecture.md#code-layout)).
> * The code still calls `DateTimeRange.pad`, which the rebuilt [`DateTimeRange`](datetime-range.md) no longer has
>   (it's replaced by `gap`), and expects the old `Worker`, so this module no longer runs as is.

### `class Slot(time, role, post)`

> [!IMPORTANT]
> **Partially implemented.** Domain building, constraint generation, constraint propagation and the MRV/degree
> ordering exist. `assign` is a stub: its effects on scoring, the `Trail` and constrained slots are not implemented.

A single schedule slot, filled by a single worker of the appropriate role. Slots are the **variables** of the CSP
(see [CSP formulation](../../explanation/csp-formulation.md)).

The constructor applies unary constraints immediately: the slot's domain contains only workers who are available
for the whole of `time` and have `role`. It creates **no** binary constraints; those are generated afterwards with
`gen_time_constraints`.

**Parameters**

* `time` — `DateTimeRange`, the period of this slot.
* `role` — `str | None`, the role required for this slot. `None` (or `"any"`) means any worker may fill it.
* `post` — `Post`, the post this slot belongs to.

#### Class variables

| Name               | Default | Description |
|--------------------|---------|-------------|
| `DEFAULT_MIN_REST` | `6`     | Default minimum rest period, in hours. Any two slots less than this far apart (including overlapping slots) get a difference constraint between them. |
| `worker_list`      | `[]`    | The full domain: all workers. Each slot copies and prunes this list. **Must be initialized before any `Slot` is created.** |
| `iteration_ticker` | `0`     | Global iteration counter used during constraint propagation. A slot whose `last_iteration` is below it hasn't been checked in the current propagation round. |

#### Attributes

| Name                     | Type           | Description |
|--------------------------|----------------|-------------|
| `time`                   | `DateTimeRange`| The slot's period. |
| `post`                   | `Post`         | The post this slot belongs to. |
| `assigned`               | `Worker \| None` | The worker assigned to this slot, initially `None`. |
| `domain`                 | `list[Worker]` | Workers who can still be assigned to this slot. |
| `diff_constrained`       | `set[Slot]`    | Slots this slot has a difference constraint with. |
| `same_shift`             | `set[Slot]`    | The other slots that, together with this one, make up a single shift. |
| `last_iteration`         | `int`          | The last propagation round in which this slot was checked. |
| `unassigned_constraints` | `int`          | Number of slots constrained with this slot that are still unassigned (used by the degree heuristic). |

#### Comparison

* `<` and `==` compare slots by `time`.
* `csp_lt(other) -> bool` is an alternative "less than" based on CSP heuristics (see
  [Search algorithm](../../explanation/search-algorithm.md#variable-ordering)): `True` if this slot's domain is
  smaller than `other`'s (MRV), or if the domains are the same size and this slot has more unassigned constrained
  slots (degree heuristic).

#### Methods

##### `gen_time_constraints(slots, min_rest=DEFAULT_MIN_REST) -> None` (static)

Generates time-based difference constraints between all the given slots.

* `slots` — `list[Slot]`, sorted by time.
* `min_rest` — minimum rest period, in hours.

Each slot is checked (with `find_time_constraints`) against the slots after it in the list.

##### `find_time_constraints(slots, min_rest) -> None`

Creates a difference constraint between this slot and every slot in `slots` that is time-constrained with it, i.e.
that overlaps it or falls within `min_rest` of it. Constraints are recorded on both slots (`diff_constrained`), and
both slots' `unassigned_constraints` counters are incremented.

* `slots` — `list[Slot]` sorted by time, beginning with slots whose time overlaps this one. Because the list is
  sorted, checking stops at the first slot that isn't time-constrained.
* `min_rest` — `datetime.timedelta`, the minimum rest period between two assignments.

##### `set_same_shift(slots) -> None` (static)

Marks the given slots as belonging to the same shift: each slot's `same_shift` is set to all the other slots in the
list.

##### `propagate_constraint(to_remove) -> bool`

Propagates a constraint following the removal of the `Worker` `to_remove` from this slot's domain.

* If this slot is already assigned, or was already checked in the current propagation round, nothing happens.
* If `to_remove` isn't in the domain, the slot is marked as checked for this round and propagation stops here.
* If the domain becomes empty, the slot (and with it the schedule) is **unsatisfiable**.
* If exactly one worker remains, that worker is assigned with `assign`, which propagates further.

**Returns** `True` if the slot remains satisfiable, `False` otherwise.

##### `assign(worker) -> bool`

> [!WARNING]
> **Not yet implemented** beyond checking that `worker` is in the domain.

Assigns `worker` to this slot and triggers constraint propagation. If propagation leaves some slot with an empty
domain, the schedule becomes unsatisfiable. Planned effects:

* update the scores affected by the assignment (see [Scoring](../../explanation/scoring.md));
* record every change so it can be undone (see
  [Search algorithm](../../explanation/search-algorithm.md#undo));
* update `unassigned_constraints` on all constrained slots.

**Returns** `True` if the schedule remains satisfiable after the assignment, `False` otherwise.
**Raises** `KeyError` if `worker` isn't in this slot's domain.

#### Open TODOs in the code

* Report to a worker when they're included in a slot's domain.
* Possibly sort the domain in a way that benefits the CSP algorithm.
