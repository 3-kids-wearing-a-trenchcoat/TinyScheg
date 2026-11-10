# `worker` module

Source: [`src/tinyscheg/model/worker.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/worker.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_worker.py`).

## Constants

| Name             | Value     | Description |
|------------------|-----------|-------------|
| `ANY_ROLE`       | `"any"`   | The wildcard role: every worker has it, including workers with no roles. |
| `NAME_SEPARATOR` | `" & "`   | Joins the names of workers sharing a cell in the [output grid](../output-format.md); worker names must not contain it. |

## `class Worker(name, roles=frozenset(), unavailable=(), likes=frozenset(), dislikes=frozenset())`

A worker who can be assigned to slots. Workers are immutable and hashable, and hold no scoring or search state:
each worker's penalty is calculated by the planned `scoring` package (see
[Scoring](../../explanation/scoring.md)), and domains and assignments belong to the search state.

**Parameters**

* `name` — `str`, the worker's name. Names are unique (checked by [validation](parsing.md#validateschedule_input)).
* `roles` — the roles this worker has; stored as a `frozenset[str]`.
* `unavailable` — the [`DateTimeRange`](datetime-range.md)s during which the worker can't be assigned; stored as a
  `tuple`, sorted by time.
* `likes`, `dislikes` — **names** of the workers this worker likes, or doesn't like, sharing a shift with; stored
  as `frozenset[str]`.

Any iterable is accepted for the collections; they're converted to the stored types.

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `has_role(role)` | `bool` | `True` if the worker has `role`. Every worker has `"any"`. |
| `is_available(time_range)` | `bool` | `True` if the `DateTimeRange` `time_range` doesn't overlap any of the worker's unavailability. A range that only touches an unavailability, ending as it starts or starting as it ends, is available. |
| `likes_worker(other)` | `bool` | `True` if this worker likes the `Worker` `other` (by name). |
| `dislikes_worker(other)` | `bool` | `True` if this worker dislikes the `Worker` `other` (by name). |

Workers don't need any CSP-specific ordering or comparison: since the search doesn't stop at the first solution,
the order in which values (workers) are tried doesn't matter. See
[ADR 0003](../../decisions/0003-variable-ordering-mrv-degree.md).
