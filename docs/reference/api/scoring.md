# `scoring` package

Sources: [`src/tinyscheg/scoring/constants.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/scoring/constants.py) and
[`src/tinyscheg/scoring/penalty.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/scoring/penalty.py)

See [Scoring](../../explanation/scoring.md) for the formulas and why, and
[`ScoringParameters`](schedule-input.md#class-scoringparameterslikes_weight-workload_weight-rest_weight-workload_power-rest_factor-neutral_partner)
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
* `workers` — a `WorkerConstants` per worker, in input order.
* `shared_slots` — $n_\text{shared}$, the number of slots in shifts of more than one slot.
* `workload_scale` — the largest possible workload penalty,
  $\sum_i \mathrm{av}_i \, (H^{\max}_i / \mathrm{av}_i)^p$ over workers with some availability.

### `class WorkerConstants`

Immutable.

* `availability` — $\mathrm{av}$, the hours within the period during which the worker is available. Overlapping
  unavailability is counted once.
* `packable_hours` — $H^{\max}$, the most hours the worker could be given.
* `worst_deficit` — $M_w$, the largest total rest deficit the worker could have.
* `likes`, `dislikes` — `frozenset[int]`, the indexes of the workers they like and dislike.

### `availability(worker, period) -> float`

The period's length minus the worker's unavailability within it.

### `packable_hours(ranges, min_rest) -> float` and `worst_deficit(ranges, min_rest, rest_factor) -> float`

$H^{\max}$ and $M_w$, each as the heaviest path through a worker's possible shifts
([ADR 0014](../../decisions/0014-exact-worst-rest-deficit.md),
[ADR 0015](../../decisions/0015-normalize-workload-by-packable-maximum.md)):

* `ranges` — the distinct time ranges of the slots in the worker's domain, sorted. Slots at the same time count once,
  since a worker can only work one of them.
* There's a step from one range to a later one when it starts at least `min_rest` after the first ends.
* For `packable_hours`, each range weighs its length; for `worst_deficit`, each step weighs the deficit it causes,
  $\max(0, \gamma \cdot |s| - \text{rest})$. A sequence's last shift has no rest after it, so no deficit.

Both take $O(n^2)$ time for $n$ ranges. Tests check them against trying every legal sequence.

### `workload_scale(workers, power) -> float`

The workload penalty's largest possible value, as above.

### `hours(length) -> float`

A `datetime.timedelta` in hours.

## `penalty` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_penalty.py`). Not yet used by the search, which takes the first
> legal schedule; branch and bound will use it.

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

### `likes_penalty(constants, assignment) -> float`

$\mathcal{L}^{**}$: for each filled slot in a shift of more than one slot, its worker's like value of the workers in
the shift's other slots, averaged over those other slots; normalized by $\beta \cdot n_\text{shared}$ and scaled to
$[0, k]$. The like values are named constants with $\beta$ as the unit: `LIKED_PARTNER = 0.0`,
`DISLIKED_PARTNER = 1.0`, and a neutral partner is `neutral_partner` times `DISLIKED_PARTNER`. 0 if every shift has
one slot.

### `workload_penalty(constants, assignment) -> float`

$\mathcal{W}^*$: the sum of $\mathrm{av} \cdot (\text{assigned hours} / \mathrm{av})^p$ over workers with some
availability, divided by `workload_scale` and scaled to $[0, k]$. 0 if no worker can be assigned anything.

### `rest_penalty(constants, assignment) -> float`

$\mathcal{R}^{**}$: for each worker, the sum over their consecutive shifts of
$\max(0, \gamma \cdot |s| - \text{rest after } s)$, divided by their `worst_deficit`. Workers whose worst deficit is
0 can never have one, and count 0.

