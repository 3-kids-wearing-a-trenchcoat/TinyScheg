# `Worker` module

Source: [`src/tinyscheg/model/worker.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/worker.py)

> [!IMPORTANT]
> **Partially implemented, with known bugs.** The constructor crashes when `unavailable` is omitted and doesn't set
> `likes` when it's omitted, and `likes`/`dislikes` are given as names while the methods below expect `Worker`
> objects. It also still calls `DateTimeRange.is_before`, which the rebuilt
> [`DateTimeRange`](datetime-range.md) no longer has. The module is due to be rebuilt.

## `class Worker(name, roles=None, unavailable=None, likes=None, dislikes=None)`

A single worker that can be assigned in the schedule.

**Parameters**

* `name` — `str`, the worker's name. Names are unique.
* `roles` — list of `str`, the roles this worker has. Defaults to an empty list.
* `unavailable` — list of pairs of ISO 8601 strings, the date-time ranges during which the worker is unavailable.
  Each pair is converted with [`parse_range`](datetime-range.md#parse_rangestr_pair) and the list is kept sorted.
  Defaults to an empty list.
* `likes` — list of workers this worker likes sharing a shift with. Defaults to an empty list.
* `dislikes` — list of workers this worker doesn't like sharing a shift with. Defaults to an empty list.

### Attributes

| Name          | Type                  | Description |
|---------------|-----------------------|-------------|
| `name`        | `str`                 | Worker name. |
| `roles`       | `list[str]`           | Roles this worker has. |
| `unavailable` | `list[DateTimeRange]` | Unavailability ranges, sorted. |
| `likes`       | list                  | Workers this worker likes. |
| `dislikes`    | list                  | Workers this worker dislikes. |

### Methods

| Method                          | Returns | Description |
|---------------------------------|---------|-------------|
| `likes_worker(other)`           | `bool`  | `True` if this worker likes the `Worker` `other`. Raises `TypeError` if `other` isn't a `Worker`. |
| `dislikes_worker(other)`        | `bool`  | `True` if this worker dislikes the `Worker` `other`. Raises `TypeError` if `other` isn't a `Worker`. |
| `is_available(period)`          | `bool`  | `True` if the `DateTimeRange` `period` doesn't overlap any of this worker's unavailability ranges. |
| `has_role(required_role)`       | `bool`  | `True` if the worker has `required_role`. `None` and `"any"` are equivalent wildcards that every worker has. |
| `_prune_unavailability_list(other_time)` | `None` | *Internal.* Removes all unavailability ranges ending before `other_time` (a `datetime.datetime`, or a `DateTimeRange` whose start is used). This reduces the number of ranges checked while building slot domains in time order. |

Workers hold no scoring or search state: each worker's penalty is calculated by the planned `scoring` package (see
[Scoring](../../explanation/scoring.md)), and domains and assignments belong to the search state.

Workers don't need any CSP-specific ordering or comparison: since the search doesn't stop at the first solution,
the order in which values (workers) are tried doesn't matter. See
[ADR 0003](../../decisions/0003-variable-ordering-mrv-degree.md).
