# Input format

> [!NOTE]
> **Implemented**, by the [`parsing`](api/parsing.md) package. See also the annotated
> [`exampleInput.yml`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/exampleInput.yml).

TinyScheg's input is a single YAML file with three top-level keys, `settings`, `workers` and `posts`, and an
optional fourth, [`history`](#history). The file is read as UTF-8, so names may be written in any script (e.g.
Hebrew).

* The first three keys are required, and `workers` and `posts` must each list at least one entry.
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
| `min_rest` | number (hours)            | Minimum time between two shifts assigned to the same worker (hard constraint). At least 0; if omitted, defaults to 6 hours. A worker's shifts are never back to back, even at 0. |
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
| `weights`         | mapping of `likes`, `workload`, `rest` to numbers | 9/34, 20/34, 5/34 (0.45 : 1 : 0.25) | What each part of the score is multiplied by: how a disliked pairing, a shift of imbalance and a short rest trade against each other ([ADR 0032](../decisions/0032-flat-penalty-parts.md), defaults from [ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)). Each at least 0, not all 0. They're relative: each is divided by their sum. An omitted key keeps its default weight, before dividing: `{likes: 0}` gives 0, 20/34 and 5/34, i.e. 0, 0.8 and 0.2. |
| `workload_power`  | whole number                          | 2              | How harshly unequal workloads are penalized. At least 2; higher values lean harder on the most loaded workers. |
| `neutral_partner` | number                                | 0.44           | How bad sharing a shift with a neutral worker is, relative to a disliked one (a liked one costs nothing). More than 0, less than 0.5, so that disliking a partner counts more than liking one ([ADR 0023](../decisions/0023-dislikes-outweigh-likes.md)). |
| `shift_share`     | number                                | 0.5            | How much each shift counts in itself, rather than by its hours, when comparing workloads. From 0 (only hours count) to 1 (every shift counts the same, however long), so that several short shifts can weigh more than one long one ([ADR 0026](../decisions/0026-workload-counts-shifts-and-hours.md)). |

```yaml
settings:
  time: ["2025-01-01", "2025-01-04"]
  scoring:
    weights: {likes: 1, workload: 2, rest: 1}
    shift_share: 0.25
```

There's no rest factor to set: the rest targets are derived from the input
([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)). An input that still sets
`rest_factor` is rejected: `settings, scoring: rest_factor is no longer a setting: the rest targets are derived from
the input (ADR 0036); remove it`.

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

## `history`

> [!NOTE]
> **Implemented.** The section is read and checked, and the schedule is searched as the continuation of the
> previous ones ([ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md)).

The previous schedules this one extends ([ADR 0029](../decisions/0029-schedule-history-input.md)), so that the
minimum rest holds across the boundary and fairness carries over
([ADR 0030](../decisions/0030-history-in-scoring.md), [ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md)): the
history's shifts are treated as the already-filled first part of one schedule, which the search continues. Optional;
each entry is a previous schedule's input file and
the schedule file written for it:

| Field      | Type   | Required | Meaning |
|------------|--------|----------|---------|
| `input`    | string | yes      | The previous schedule's input file. |
| `schedule` | string | yes      | Its schedule file (`.csv`, `.xlsx` or `.ods`), as written by TinyScheg, possibly edited by hand since. |

```yaml
history:
  - input: "day1.yml"
    schedule: "day1_schedule.xlsx"
  - input: "day2.yml"
    schedule: "day2_schedule.xlsx"
```

* **Paths are relative to this input file**, not to where TinyScheg runs.
* **Each schedule file is read with its own input**, which may differ from this one in anything: posts, hours, shift
  lengths, workers and settings. Workers are matched across inputs by name.
* A history input's own `history` is ignored: this input lists every previous schedule it counts, so how far back
  fairness reaches is set here.
* Every history period must **end by the time this one starts**, and no two may overlap. Entries can be in any order.
* A worker of a previous schedule who isn't in this input (they've left) gets a warning, and their history is
  ignored. A worker of this input who isn't in a previous one (they've joined) counts as unavailable during it.

## Errors

Input is checked in two stages, and each stage reports every problem it finds at once:

1. **Structure** — missing required fields, unknown fields, wrong types and invalid values (e.g. `length: 0`, a
   time window `"25:00-07:00"`, or a range whose start isn't before its end).
2. **Rules spanning several entries** — checked only once the structure is valid:
    * worker names are unique, and so are post names;
    * no worker name contains `" & "`;
    * every name in a worker's `likes` and `dislikes` is another existing worker (not the worker themselves), and no
      name is in both;
    * a post's variations don't overlap;
    * the history's periods end by the time this one starts, and don't overlap each other.

A history entry whose files can't be read, or whose schedule doesn't match its input (a missing post column or
shift row, a wrong number of names, an unknown worker), is reported in the first stage, naming the entry. Problems in
a history input are reported with the entry's name in front.

Each message names where the problem is, counting entries from 1 in the order they appear:

```
invalid input:
  - worker #3 ("Jeff"), likes: unknown worker "Jil"
  - post #1 ("front gate"), variation #1 (19:00-07:00) and variation #2 (06:00-08:00) overlap
  - history entry #1 ("day1.yml"), schedule 'day1_schedule.xlsx': desk at 2025-01-01T08:00:00: unknown worker 'Jil'
```
