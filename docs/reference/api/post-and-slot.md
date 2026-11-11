# `post`, `shift` and `shift_generation` modules

Sources: [`src/tinyscheg/model/post.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/post.py),
[`src/tinyscheg/model/shift.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/shift.py) and
[`src/tinyscheg/model/shift_generation.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/shift_generation.py)

See [Domain model](../../explanation/domain-model.md) for how posts, shifts and slots relate to each other.

## `post` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_post.py`). Shifts are generated from posts by the
> [`shift_generation` module](#shift_generation-module).

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

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_shift_generation.py`).

Shifts and slots are plain, immutable, hashable descriptions of what needs filling. Who fills them, and who still
can, is part of the search state (see [Architecture](../../explanation/architecture.md#code-layout)), not of these
objects.

### `class Shift(index, post, time, slots)`

One post being manned for one continuous time range.

* `index` — `int`, the shift's position in the stable shift order.
* `post` — `Post`, the post being manned.
* `time` — `DateTimeRange`, when.
* `slots` — `tuple[Slot, ...]`, one per required worker, in the order of the post's roles. A shift's slots are
  contiguous in the stable slot order.

### `class Slot(index, shift_index, post, time, role)`

A place for one worker of one role in a shift: a **variable** of the CSP
(see [CSP formulation](../../explanation/csp-formulation.md)).

* `index` — `int`, the slot's position in the stable slot order. The CSP refers to slots by this index.
* `shift_index` — `int`, the `index` of the slot's shift. A slot refers to its shift by index rather than holding it,
  since two immutable objects can't hold each other.
* `post`, `time` — the shift's post and time range, repeated so that constraint and scoring code doesn't need to
  look the shift up.
* `role` — `str`, the role the slot requires (`"any"` for any worker).

## `shift_generation` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_shift_generation.py`).

Generates the shifts and slots of a schedule by segments
([ADR 0018](../../decisions/0018-slot-generation-by-segments.md); see
[Domain model](../../explanation/domain-model.md#shifts-and-slots)).

### `generate_shifts(posts, period) -> tuple[Shift, ...]`

Every shift of the schedule, with its slots.

* `posts` — the `Post`s, in input order.
* `period` — `DateTimeRange`, the schedule period.

**Returns** the shifts in stable order: by start, end, then the post's position in `posts`. Each shift's slots are
created in role order, `count` slots per role, and numbered in the same order across all shifts. A segment whose
rules need no workers (a variation with `roles: {}`) produces **no shifts**: the post is closed there.

### `all_slots(shifts) -> tuple[Slot, ...]`

Every slot of the given shifts, in stable order; a slot's `index` is its position in the result.

### `segments(post, period) -> list[tuple[DateTimeRange, ShiftRules]]`

Splits a post's active time into segments, in time order, each with the rules in effect: a variation's where one
applies, otherwise the post's general rules. The post is active for the whole period if it has no `window`,
otherwise during each occurrence of its window (`active_ranges(post, period)`), including one that opened the day
before the period starts. Variations only apply while the post is active.

Since every occurrence of a daily window is its own active range, a 24-hour window such as `"06:00-06:00"` puts a
segment boundary at 06:00 every day, while a post with no `window` has no daily boundary.

### `shift_times(segment, rules) -> list[DateTimeRange]`

Lays shifts of `rules.length` back to back from the segment's start; the last one is cut off at the segment's end
(a "dangling" shift).
