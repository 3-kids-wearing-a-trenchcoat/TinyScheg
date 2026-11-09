# Input format

> [!WARNING]
> **Not yet implemented.** The format below is defined (see the annotated [`exampleInput.yml`](../../exampleInput.yml)),
> but the parser that reads it doesn't exist yet.

TinyScheg's input is a single YAML file with three top-level keys: `settings`, `workers` and `posts`.

## `settings`

General scheduler settings.

| Field      | Type                      | Description                                                                 |
|------------|---------------------------|-----------------------------------------------------------------------------|
| `time`     | pair of ISO 8601 strings  | The time period to generate a schedule for, as `[start, end]`.             |
| `min_rest` | number (hours)            | Minimum time between two shifts assigned to the same worker (hard constraint). If omitted, defaults to 6 hours (`Slot.DEFAULT_MIN_REST`). |

```yaml
settings:
  time: ["2025-01-01", "2025-01-04"]
  min_rest: 5
```

## `workers`

A list of workers available for assignment.

| Field         | Type                             | Required | Description |
|---------------|----------------------------------|----------|-------------|
| `name`        | string                           | yes      | Worker name. Duplicates aren't allowed. |
| `roles`       | list of strings                  | no       | Roles this worker has. |
| `unavailable` | list of pairs of ISO 8601 strings | no      | Date-time ranges during which the worker is unavailable. |
| `likes`       | list of worker names             | no       | Workers this worker likes sharing a shift with. |
| `dislikes`    | list of worker names             | no       | Workers this worker doesn't like sharing a shift with. |

* Any field other than `name` may be omitted and is then considered empty.
* A worker is assumed to be available at all times other than the ranges listed in `unavailable`.
* Date-times are ISO 8601 (`YYYY-MM-DDTHH:MM:SS`). A date without a time is taken to be midnight, so
  `["2025-01-03", "2025-01-04"]` means unavailable throughout the 3rd and available on the 4th.
* A worker shouldn't appear in both their own `likes` and `dislikes`.

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
| `roles`      | mapping of role → count     | yes      | How many workers of each role the post needs at any time. |
| `length`     | number (hours)              | yes      | Shift duration. |
| `time`       | `"HH:MM-HH:MM"`             | no       | Daily time window during which the post is active. If omitted, the post is always active. |
| `variations` | list of variations          | no       | Time-based variations of the post (see below). |

* The role `any` is a wildcard that every worker fulfills, including workers with no roles.
* The number of workers a shift needs is the sum of the role counts, so it isn't specified separately.
* A time window may cross midnight, e.g. `"19:00-07:00"` is 7 PM to 7 AM the next day.

### Variations

A variation overrides a post's fields during a recurring daily time window.

| Field    | Type                     | Required | Description |
|----------|--------------------------|----------|-------------|
| `time`   | `"HH:MM-HH:MM"`          | yes      | Daily time window during which the variation applies. |
| `roles`  | mapping of role → count  | no       | Overrides the post's `roles`. |
| `length` | number (hours)           | no       | Overrides the post's `length`. |

Any field a variation doesn't specify is inherited from the post's general case.

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
