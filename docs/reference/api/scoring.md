# `scoring` package

Sources: [`src/tinyscheg/scoring/constants.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/scoring/constants.py) and
[`src/tinyscheg/scoring/penalty.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/scoring/penalty.py)

See [Scoring](../../explanation/scoring.md) for the formulas and why, and
[`ScoringParameters`](schedule-input.md#class-scoringparameterslikes_weight-workload_weight-rest_weight-workload_power-rest_factor-neutral_partner-shift_share)
for the parameters. The package depends only on `model` and `timing`: it receives slots, shifts, workers and domains
as plain data, and the search will use it rather than the other way round. All durations are in hours, as `float`.

## `constants` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_scoring_constants.py`).

The constants every penalty is computed from, calculated once per run, before the search.

### `build_constants(settings, workers, shifts, slots, domains) -> ScoringConstants`

* `settings` — [`Settings`](schedule-input.md#class-settingsperiod-min_restdefault_min_rest-scoringscoringparameters),
  for the period, the minimum rest and the scoring parameters.
* `workers`, `shifts`, `slots` — in input and stable order, as in [`Problem`](problem.md).
* `domains` — for each slot, the indexes of the workers who can fill it, as `Problem.domains`.

### `class ScoringConstants`

Immutable.

* `parameters` — the `ScoringParameters`.
* `min_rest` — the minimum rest, in hours.
* `slots`, `shifts` — as given.
* `slot_hours` — `tuple[float, ...]`, each slot's length.
* `slot_load` — `tuple[float, ...]`, each slot's load for the workload penalty, from `slot_load`
  ([ADR 0026](../../decisions/0026-workload-counts-shifts-and-hours.md)).
* `workers` — a `WorkerConstants` per worker, in input order.
* `shared_slots` — $n_\text{shared}$, the number of slots in shifts of more than one slot.
* `workload_scale` — the largest possible workload penalty,
  $\sum_i \mathrm{av}_i \, (H^{\max}_i / \mathrm{av}_i)^p$ over workers with some availability.

### `class WorkerConstants`

Immutable.

* `availability` — $\mathrm{av}$, the hours within the period during which the worker is available. Overlapping
  unavailability is counted once.
* `packable_load` — $H^{\max}$, the most load the worker could be given.
* `worst_deficit` — $M_w$, the largest total rest deficit the worker could have.
* `likes`, `dislikes` — `frozenset[int]`, the indexes of the workers they like and dislike.

### `availability(worker, period) -> float`

The period's length minus the worker's unavailability within it.

### `slot_load(slot_hours, mean_hours, shift_share) -> float`

A slot's load: $(1 - \sigma) \cdot$ `slot_hours` $+ \; \sigma \cdot$ `mean_hours`, where `mean_hours` is the mean length
of the schedule's slots. With $\sigma = 0$ the load is the slot's hours; with $\sigma = 1$ every slot has the same load.
The total load of all slots equals their total hours.

### `packable_load(ranges, min_rest, load) -> float` and `worst_deficit(ranges, min_rest, rest_factor) -> float`

$H^{\max}$ and $M_w$, each as the heaviest path through a worker's possible shifts
([ADR 0014](../../decisions/0014-exact-worst-rest-deficit.md),
[ADR 0015](../../decisions/0015-normalize-workload-by-packable-maximum.md)):

* `ranges` — the distinct time ranges of the slots in the worker's domain, sorted. Slots at the same time count once,
  since a worker can only work one of them.
* There's a step from one range to a later one when it starts at least `min_rest` after the first ends.
* For `packable_load`, each range weighs its `load` (a function of the range); for `worst_deficit`, each step weighs the deficit it causes,
  $\max(0, \gamma \cdot |s| - \text{rest})$. A sequence's last shift has no rest after it, so no deficit.

Both take $O(n^2)$ time for $n$ ranges. Tests check them against trying every legal sequence.

### `workload_scale(workers, power) -> float`

The workload penalty's largest possible value, as above.

### `hours(length) -> float`

A `datetime.timedelta` in hours.

## `penalty` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_penalty.py`). Used by branch and bound
> ([`find_best_schedule`](search.md#find_best_scheduleproblem-constants-prunetrue-on_improvementnone-incrementaltrue-searchresult)), and by the command
> line to show the written schedule's penalty.

The penalty of a (partial) schedule. An **assignment** holds a worker index per slot, in stable slot order, or
`None` for an unfilled slot, as the search state's `assigned` list does. Unfilled slots contribute nothing.

Every penalty is computed from scratch, as a `float`, with sums always taken in the same order (shifts, slots and
workers in their stable order). The same assignment therefore always gets exactly the same penalty, however it was
reached, and filling another slot never lowers it.

### `score(constants, assignment) -> Penalty`

The penalty of a (partial) schedule.

### `class Penalty(total, likes, workload, rest)`

Immutable. `likes`, `workload` and `rest` are the normalized parts, each in $[0, k]$ for $k$ workers; `total` is
their weighted sum, $a \cdot$ `likes` $+ \; b \cdot$ `workload` $+ \; c \cdot$ `rest`, also in $[0, k]$.

### `lower_bound(constants, assignment, domains) -> float`

A lower bound on the total penalty of every complete schedule extending a partial one, for pruning
([ADR 0024](../../decisions/0024-cheapest-first-value-order-and-workload-bound.md)): the weighted
`likes_lower_bound` and `workload_lower_bound`, plus the weighted rest penalty so far. At most the total penalty of
every completion, and at least the partial schedule's own. Neither look-ahead assumes anything about shift lengths,
so it holds for asymmetric schedules.

* `domains` — for each slot, the workers who can still fill it (in the search, the current domains); only the
  unfilled slots' are used.

There's no look-ahead for rest: a worker can always be given no further shifts, so no future rest deficit is certain.

### `likes_lower_bound(constants, assignment, domains) -> float`

The lowest normalized likes penalty any completion could have. In a complete schedule, each pair of slots in a shared
shift adds both workers' like values of each other, over the shift's other slots; a pair with an unfilled slot adds at
least the lowest such value any workers still in the slots' domains could give. Each pair's best is chosen
independently (even the same worker for both), which can only lower the bound. In
$[\mathcal{L}^{**}(\text{partial}), k]$.

### `workload_lower_bound(constants, assignment, domains) -> float`

The lowest normalized workload penalty any completion could have: the unfilled slots' load spread so that the least
loaded workers are topped up to a common level of load per available hour ("water-filling"), which minimizes the
sum of convex terms. Each worker can gain at most the load of the unfilled slots whose domain they're in, so a worker
who could take little stops rising early. Which slots overlap is ignored, so it may be lower than anything
reachable. In $[\mathcal{W}^*(\text{partial}), k]$.

### `likes_penalty(constants, assignment) -> float`

$\mathcal{L}^{**}$: for each filled slot in a shift of more than one slot, its worker's like value of the workers in
the shift's other slots, averaged over those other slots; normalized by $\beta \cdot n_\text{shared}$ and scaled to
$[0, k]$. The like values are named constants with $\beta$ as the unit: `LIKED_PARTNER = 0.0`,
`DISLIKED_PARTNER = 1.0`, and a neutral partner is `neutral_partner` times `DISLIKED_PARTNER`. 0 if every shift has
one slot.

### `workload_penalty(constants, assignment) -> float`

$\mathcal{W}^*$: the sum of $\mathrm{av} \cdot (\text{assigned load} / \mathrm{av})^p$ over workers with some
availability, divided by `workload_scale` and scaled to $[0, k]$. 0 if no worker can be assigned anything.

### `rest_penalty(constants, assignment) -> float`

$\mathcal{R}^{**}$: for each worker, the sum over their consecutive shifts of
$\max(0, \gamma \cdot |s| - \text{rest after } s)$, divided by their `worst_deficit`. Workers whose worst deficit is
0 can never have one, and count 0.

### Helpers shared with the `incremental` module

`shift_likes_lower_bound(constants, shift, assignment, domains)` (one shift's share of the likes look-ahead),
`pair_like_value(constants, worker, partner)` (both workers' like values of each other), `normalized_likes(constants,
total)` and `rest_deficit(constants, earlier, later)` (one rest's deficit). Both modules use them, so that they do the
same arithmetic.

## `incremental` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_incremental.py`, against the `penalty` module as the oracle).
> Used by branch and bound ([ADR 0027](../../decisions/0027-incremental-scoring-for-steering.md)).

### `class IncrementalScore(constants, assignment, domains)`

The running totals of one search, kept in step with its assignments, for the value order and the lower bound. They
equal the `penalty` module's values up to rounding (about $10^{-14}$), and so only steer the search.

* `assignment`, `domains` — the search's own (empty) assignment list and current domains, read as the search changes
  them, never changed.

Methods:

* `total()` — the current schedule's total penalty, as `score` would give it.
* `cost_if(slot, worker)` — the total with the worker in the unfilled slot, for the value order.
* `bound()` — the lower bound, as `lower_bound` would give it.
* `assign(slot, worker, narrowed)` — update the totals after the search assigned the slot; `narrowed` is the change
  record's `saved_domains`, (slot, domain before) pairs. Only the assigned worker's load and rest, the shifts with a
  slot assigned or narrowed, and the caps of the workers dropped from a domain change.
* `undo()` — restore the totals from before the latest `assign`, exactly: saved values are put back, never
  subtracted.

**Raises** `ValueError` if the assignment isn't empty at the start.

