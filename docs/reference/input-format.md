# Input format

> [!NOTE]
> **Implemented**, by the [`parsing`](api/parsing.md) package. See also the annotated
> [`exampleInput.yml`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/exampleInput.yml).

TinyScheg's input is a single YAML file with three top-level keys: `settings`, `workers` and `posts`.
The file is read as UTF-8, so names may be written in any script (e.g. Hebrew).

* All three keys are required, and `workers` and `posts` must each list at least one entry.
* **Unknown fields are an error**, at every level. This catches typos such as `unavailble:`, which would otherwise be
  silently ignored.
* An optional field may be omitted or left empty (`likes:` with nothing after it); either way it's considered empty.
* Names are compared exactly: they're case-sensitive, and spaces aren't trimmed.
* Date-times may be quoted (`"2025-01-01"`) or not (`2025-01-01`). They must not include a timezone.

If the input is invalid, TinyScheg reports **every** problem it finds, each naming where it is (e.g.
`worker #3 ("Jeff"), likes: unknown worker "Jil"`), and stops. See [Errors](#errors).

## `settings`

General scheduler settings.

| Field      | Type                      | Description                                                                 |
|------------|---------------------------|-----------------------------------------------------------------------------|
| `time`     | pair of ISO 8601 strings  | Required. The time period to generate a schedule for, as `[start, end]`; `start` must be before `end`. |
| `min_rest` | number (hours)            | Minimum time between two shifts assigned to the same worker (hard constraint). At least 0; if omitted, defaults to 6 hours. |
| `scoring`  | mapping                   | Optional. Overrides scoring parameters; see [below](#scoring). |

```yaml
settings:
  time: ["2025-01-01", "2025-01-04"]
  min_rest: 6
```

### `scoring`

> [!NOTE]
> **Implemented** ([ADR 0022](../decisions/0022-scoring-parameters-with-defaults-and-input-overrides.md)).

Optional parameters of the [penalty score](../explanation/scoring.md#parameters) that picks the fairest schedule.
Every field is optional; an omitted field keeps its default.

| Field             | Type                                  | Default        | Description |
|-------------------|---------------------------------------|----------------|-------------|
| `weights`         | mapping of `likes`, `workload`, `rest` to numbers | 0.25, 0.5, 0.25 | How much each part of the score counts. Each at least 0, not all 0. They're relative: each is divided by their sum, so `{likes: 1, workload: 2, rest: 1}` means the same as the default. An omitted key keeps its default weight, before dividing: `{likes: 0}` gives 0, 0.5 and 0.25, i.e. 0, ⅔ and ⅓. |
| `workload_power`  | whole number                          | 2              | How harshly unequal workloads are penalized. At least 2; higher values lean harder on the most loaded workers. |
| `rest_factor`     | number                                | 3              | The ideal rest after a shift, as a multiple of its length. At least 1. Only rest targets longer than `min_rest` have an effect. |
| `neutral_partner` | number                                | 1/3 (0.333…)   | How bad sharing a shift with a neutral worker is, relative to a disliked one (a liked one costs nothing). More than 0, less than 0.5, so that disliking a partner counts more than liking one ([ADR 0023](../decisions/0023-dislikes-outweigh-likes.md)). |

```yaml
settings:
  time: ["2025-01-01", "2025-01-04"]
  scoring:
    weights: {likes: 1, workload: 2, rest: 1}
    rest_factor: 2.5
```

## `workers`

A list of workers available for assignment.

| Field         | Type                             | Required | Description |
|---------------|----------------------------------|----------|-------------|
| `name`        | string                           | yes      | Worker name. Duplicates aren't allowed, and it must not contain `" & "` (used to join names in the [output](output-format.md)). |
| `roles`       | list of strings                  | no       | Roles this worker has. |
| `unavailable` | list of pairs of ISO 8601 strings | no      | Date-time ranges during which the worker is unavailable. |
| `likes`       | list of worker names             | no       | Workers this worker likes sharing a shift with. |
| `dislikes`    | list of worker names             | no       | Workers this worker doesn't like sharing a shift with. |

* Any field other than `name` may be omitted and is then considered empty.
* A worker is assumed to be available at all times other than the ranges listed in `unavailable`. Each range's start
  must be before its end.
* Date-times are ISO 8601 (`YYYY-MM-DDTHH:MM:SS`). A date without a time is taken to be midnight, so
  `["2025-01-03", "2025-01-04"]` means unavailable throughout the 3rd and available on the 4th.
* Every name in `likes` and `dislikes` must be the name of another worker in the list: a worker can't like or
  dislike themselves, or like and dislike the same worker.

```yaml
workers:
  - name: "Jack"
    roles: ["supervisor", "other"]
    unavailable:
      - ["2025-01-01T04:00:00", "2025-01-01T06:00:00"]
    likes: ["Jill"]
    dislikes: []

  - name: "Anne"   # no roles, always available, no preferences
```

## `posts`

A list of posts that need to be manned throughout the schedule.

| Field        | Type                        | Required | Description |
|--------------|-----------------------------|----------|-------------|
| `name`       | string                      | yes      | Post name. Duplicates aren't allowed. |
| `roles`      | mapping of role → count     | yes      | How many workers of each role the post needs at any time. Counts are whole numbers of at least 0. |
| `length`     | number (hours)              | yes      | Shift duration; more than 0, and may be fractional (`2.5`). |
| `time`       | `"HH:MM-HH:MM"`             | no       | Daily time window during which the post is active. If omitted, the post is always active. |
| `variations` | list of variations          | no       | Time-based variations of the post (see below). |

* The role `any` is a wildcard that every worker fulfills, including workers with no roles.
* The number of workers a shift needs is the sum of the role counts, so it isn't specified separately. A count of 0,
  or no roles at all (`roles: {}`), is allowed: such shifts need no workers.
* The order of the roles matters only for the stable order of slots, which keeps results deterministic.
* A time window may cross midnight, e.g. `"19:00-07:00"` is 7 PM to 7 AM the next day.

### Variations

A variation overrides a post's fields during a recurring daily time window.

| Field    | Type                     | Required | Description |
|----------|--------------------------|----------|-------------|
| `time`   | `"HH:MM-HH:MM"`          | yes      | Daily time window during which the variation applies. |
| `roles`  | mapping of role → count  | no       | Overrides the post's `roles`. |
| `length` | number (hours)           | no       | Overrides the post's `length`. |

* Any field a variation doesn't specify is inherited from the post's general case.
* A variation only applies while its post is active: if the post has its own `time` window, the variation is limited
  to the part of its window that falls within the post's.
* Variations of the same post must not overlap in time; overlapping variations are an input error.
* A variation may require no workers at all (e.g. `roles: {}`), which closes the post during its window.

### Time windows

* `"HH:MM-HH:MM"` windows recur every day. A window whose end is earlier than its start crosses midnight
  (`"19:00-07:00"` is 7 PM to 7 AM the next day), and a window whose start equals its end (`"00:00-00:00"`) covers
  the full 24 hours.
* Shifts start at the beginning of each window, and a shift is cut short where the window (or the schedule) ends.
  See [Domain model](../explanation/domain-model.md#shifts-and-slots) for exactly how shifts are generated.

```yaml
posts:
  - name: "front gate"
    roles:
      any: 1
    length: 3
    variations:
      # every day from 7 PM to 7 AM, two workers, one of which must have the security role
      - time: "19:00-07:00"
        roles:
          security: 1
          any: 1

  - name: "desk"
    roles:
      supervisor: 1
    time: "08:00-20:00"
    length: 4
```

## Errors

Input is checked in two stages, and each stage reports every problem it finds at once:

1. **Structure** — missing required fields, unknown fields, wrong types and invalid values (e.g. `length: 0`, a
   time window `"25:00-07:00"`, or a range whose start isn't before its end).
2. **Rules spanning several entries** — checked only once the structure is valid:
    * worker names are unique, and so are post names;
    * no worker name contains `" & "`;
    * every name in a worker's `likes` and `dislikes` is another existing worker (not the worker themselves), and no
      name is in both;
    * a post's variations don't overlap.

Each message names where the problem is, counting entries from 1 in the order they appear:

```
invalid input:
  - worker #3 ("Jeff"), likes: unknown worker "Jil"
  - post #1 ("front gate"), variation #1 (19:00-07:00) and variation #2 (06:00-08:00) overlap
```
