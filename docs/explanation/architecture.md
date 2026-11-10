# Architecture

TinyScheg runs as a pipeline of five stages:

```mermaid
flowchart LR
    A[Parse input] --> B[Initialize] --> C[Run CSP search] --> D[Build output] --> E[Return output]
```

## 1. Parse input

> [!WARNING]
> **Not yet implemented.**

Read the YAML input file (see [Input format](../reference/input-format.md)) and turn it into objects:

* each worker entry becomes a [`Worker`](../reference/api/worker.md);
* each post entry becomes a [`Post`](../reference/api/post-and-slot.md#class-postname-length-roles-periodnone-variationsnone).
  This includes converting daily time windows (e.g. `"19:00-07:00"`) into concrete date-time ranges over the
  schedule period, and filling in each variation's unspecified fields from the post's general case.

The input is also **validated**: names are unique, every name in a likes/dislikes list refers to an existing worker,
a worker isn't in their own lists, nobody is both liked and disliked by the same worker, and a post's variations
don't overlap. Invalid input is reported before anything else happens.

## 2. Initialize

> [!IMPORTANT]
> **Partially implemented.** The building blocks exist (`Post.gen_slot_list`, `Slot` domain building and
> `Slot.gen_time_constraints`), but nothing ties them together yet.

Set up the CSP:

1. Generate the slots of every post over the schedule period, segment by segment (see
   [Domain model](domain-model.md#shifts-and-slots)), in their stable order. Each slot's domain is pruned by unary
   constraints (availability, role) as it's created.
2. Generate the binary difference constraints between slots, using the minimum rest period from the settings.
3. Calculate the constants used by scoring: each worker's availability, the number of shared slots, and each
   worker's worst rest deficit and packable maximum (see [Scoring](scoring.md)).
4. If any slot's domain is already empty, no legal schedule exists: report it and stop.

See [Domain model](domain-model.md) and [CSP formulation](csp-formulation.md).

## 3. Run CSP search

> [!WARNING]
> **Not yet implemented.**

Search for the best schedule: a backtracking search with constraint propagation, ordered by MRV and the degree
heuristic, pruned by comparing each partial schedule's penalty against the best complete schedule found so far.
See [Search algorithm](search-algorithm.md) and [Scoring](scoring.md).

## 4. Build output

> [!WARNING]
> **Not yet implemented.**

Transform the best schedule's list of assigned slots into the output CSV (see
[Output format](../reference/output-format.md)).

## 5. Return output

> [!WARNING]
> **Not yet implemented.**

Write or return the output.

## Code layout

All code currently lives directly in `src/`:

| File                  | Contents |
|-----------------------|----------|
| `src/DateTimeRange.py`| [`DateTimeRange`](../reference/api/datetime-range.md) and `parse_range` |
| `src/Worker.py`       | [`Worker`](../reference/api/worker.md) |
| `src/shift.py`        | [`Post` and `Slot`](../reference/api/post-and-slot.md) |
| `src/main.py`         | Entry point (empty) |

Planned but not yet in code: `Scorer`, `Schedule` and the search with its explicit search state.
