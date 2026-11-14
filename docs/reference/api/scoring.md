# `scoring` package

Sources: [`src/tinyscheg/scoring/constants.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/scoring/constants.py) and
[`src/tinyscheg/scoring/penalty.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/scoring/penalty.py)

See [Scoring](../../explanation/scoring.md) for the formulas and why, and
[`ScoringParameters`](schedule-input.md#class-scoringparameterslikes_weight-workload_weight-rest_weight-workload_power-neutral_partner-shift_share)
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
* `domains` — for each slot, the indexes of the workers who could fill it from scratch, as `Problem.scoring_domains`:
  with a history, every worker who could have filled a history slot, not only the one who did ([ADR 0037](../../decisions/0037-worst-rest-deficit-from-scratch-over-the-history.md)). Only the
  worst rest deficits use it.

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
* `workload_unit` — $u_W$, the unit the workload penalty is measured in
  ([ADR 0032](../../decisions/0032-flat-penalty-parts.md)): (mean slot load)$^p$ / (mean availability)$^{p-1}$, over
  the workers with some availability; 0 if there are none.
* `rest_unit` — $\bar{M}$, the mean `worst_deficit` of the workers who could have one; 0 if none can.
* `rest_factor` — $\gamma$, from `rest_factor` below ([ADR 0036](../../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)).
* `unavailable_at_start`, `unavailable_at_end` — `tuple[tuple[float, ...], ...]`: for each worker and slot, the
  worker's unavailable hours before the slot starts and ends, from `unavailable_before`; a rest's available time is
  its length less the difference ([ADR 0038](../../decisions/0038-rests-count-only-available-time.md)).
* `rest_scale` — $\tau = \gamma \cdot \overline{|s|}$, one typical rest target (the mean slot length times $\gamma$),
  the unit each worker's squared hours short are measured in.
* `pair_values` — `tuple[tuple[float, ...], ...]`: `pair_values[w][p]` is what workers `w` and `p` add to the likes
  total as a pair, before dividing by the shift's other slots: both their like values of each other, from
  `pair_values`. Computed once, since the search asks for them at every step.

### `class WorkerConstants`

Immutable.

* `availability` — $\mathrm{av}$, the hours within the period during which the worker is available. Overlapping
  unavailability is counted once.
* `worst_deficit` — $M_w$, the largest total rest deficit the worker could have.
* `likes`, `dislikes` — `frozenset[int]`, the indexes of the workers they like and dislike.

### `availability(worker, period) -> float`

The period's length minus the worker's unavailability within it.

### `slot_load(slot_hours, mean_hours, shift_share) -> float`

A slot's load: $(1 - \sigma) \cdot$ `slot_hours` $+ \; \sigma \cdot$ `mean_hours`, where `mean_hours` is the mean length
of the schedule's slots. With $\sigma = 0$ the load is the slot's hours; with $\sigma = 1$ every slot has the same load.
The total load of all slots equals their total hours.

### `rest_factor(available, slot_hours) -> float` and `rest_target(rest_factor, earlier_hours, later_hours) -> float`

The rest factor and the rest targets ([ADR 0036](../../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)):

* `rest_factor` — $\gamma = (\sum \text{available} - H) / H$, $H$ the total of `slot_hours`: the schedule's free
  hours per hour of work. 0 if there are no slots.
* `rest_target` — the target for the rest between two consecutive shifts of a worker,
  $\gamma \cdot (\text{earlier} + \text{later}) / 2$: the same two shifts get the same target in either order.

### `unavailable_before(unavailable, moment) -> float`

How many hours of a worker's unavailability (sorted, as `Worker` keeps it; overlaps count once) fall before a
moment; 0.0 exactly if none does ([ADR 0038](../../decisions/0038-rests-count-only-available-time.md)).

### `worst_deficit(ranges, min_rest, rest_factor, unavailable=()) -> float`

$M_w$, as the heaviest path through a worker's possible shifts
([ADR 0014](../../decisions/0014-exact-worst-rest-deficit.md)):

* `ranges` — the distinct time ranges of the slots in the worker's domain, sorted. Slots at the same time count once,
  since a worker can only work one of them.
* There's a step from one range to a later one when it starts at least `min_rest` after the first ends.
* Each step weighs the deficit it causes, $\max(0, \text{rest target} - \text{rest})$, the target from `rest_target`
  and the rest in available time: less the worker's `unavailable` time within it (ADR 0038). Which steps are legal
  stays on the clock. A sequence's last shift has no rest after it, so no deficit.

It takes $O(n^2)$ time for $n$ ranges. Tests check it against trying every legal sequence.

### `integer_power(base, exponent) -> float`

`base` raised to a whole `exponent`, multiplied out one factor at a time; the workload part's powers use it. Python's
`float ** int` rounds differently in the last digit from one interpreter to another (CPython's `pow` differs from
repeated multiplication for about one value in a thousand), which could make CPython and PyPy break a tie
differently; multiplication rounds the same on both.

### `workload_unit(workers, loads, power) -> float` and `rest_unit(workers) -> float`

The two units above ([ADR 0032](../../decisions/0032-flat-penalty-parts.md)). Measured in them, one shift of imbalance
and the average hour short cost the same at any schedule length.

### `like_value(worker, partner, neutral_partner) -> float` and `pair_values(workers, neutral_partner)`

`like_value` is $l(\text{partner})$ for a worker (a `WorkerConstants`): `LIKED_PARTNER` for a liked partner,
`DISLIKED_PARTNER` for a disliked one, and `neutral_partner` times `DISLIKED_PARTNER` for anyone else. The like values
are named constants with $\beta$ as the unit: `LIKED_PARTNER = 0.0`, `DISLIKED_PARTNER = 1.0`. `pair_values` gives
the table of every pair's value, the same worker twice included (the likes look-ahead may ask for it).

### `hours(length) -> float`

A `datetime.timedelta` in hours.

## `penalty` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_penalty.py`). Used by branch and bound
> ([`find_best_schedule`](search.md#find_best_scheduleproblem-constants-prunetrue-on_improvementnone-incrementaltrue-on_progressnone-keep_best_on_interruptfalse-searchresult)), and by the command
> line to show the written schedule's penalty.

The penalty of a (partial) schedule. An **assignment** holds a worker index per slot, in stable slot order, or
`None` for an unfilled slot, as the search state's `assigned` list does. Unfilled slots contribute nothing.

Every penalty is computed from scratch, as a `float`, with sums always taken in the same order (shifts, slots and
workers in their stable order). The same assignment therefore always gets exactly the same penalty, however it was
reached, and filling another slot never lowers it.

### `score(constants, assignment) -> Penalty`

The penalty of a (partial) schedule.

### `class Penalty(total, likes, workload, rest)`

Immutable. `likes`, `workload` and `rest` are the parts before weighting, each in its own units
([ADR 0032](../../decisions/0032-flat-penalty-parts.md)) and at least 0; `total` is their weighted sum,
$a \cdot$ `likes` $+ \; b \cdot$ `workload` $+ \; c \cdot$ `rest`. Only differences between schedules mean anything.

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

The lowest likes penalty any completion could have. In a complete schedule, each pair of slots in a shared
shift adds both workers' like values of each other, over the shift's other slots; a pair with an unfilled slot adds at
least the lowest such value any workers still in the slots' domains could give. Each pair's best is chosen
independently (even the same worker for both), which can only lower the bound. At least
$\mathcal{L}^{**}(\text{partial})$.

### `workload_lower_bound(constants, assignment, domains) -> float`

The lowest workload penalty any completion could have: the unfilled slots' load spread so that the least
loaded workers are topped up to a common level of load per available hour ("water-filling"), which minimizes the
sum of convex terms. Each worker can gain at most the load of the unfilled slots whose domain they're in, so a worker
who could take little stops rising early. Which slots overlap is ignored, so it may be lower than anything
reachable. At least $\mathcal{W}^*(\text{partial})$.

### `likes_penalty(constants, assignment) -> float`

$\mathcal{L}^{**}$: for each filled slot in a shift of more than one slot, its worker's like value of the workers in
the shift's other slots, averaged over those other slots; in units of $\beta$, a disliked partner. The like values are those of `like_value`
in the `constants` module. 0 if every shift has one slot.

### `workload_penalty(constants, assignment) -> float`

$\mathcal{W}^*$: the sum of $\mathrm{av} \cdot (\text{assigned load} / \mathrm{av})^p$ over workers with some
availability, divided by `workload_unit`. 0 if no worker can be assigned anything.

### `rest_penalty(constants, assignment) -> float`

$\mathcal{R}^{**}$ ([ADR 0036](../../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)): for each worker, their deficit $D_w$, the sum over their consecutive shifts of
$\max(0, \text{rest target} - \text{rest})$, and their term `rest_unit` / `worst_deficit` $\cdot D_w^{p_R} /$
`rest_scale`, with $p_R$ = `REST_POWER` (2, so squared; multiplied out one factor at a time, which rounds the same on
every interpreter): squared, so the same shortfall costs more on a worker who already has some, and weighing more for a
worker who could rarely be short. Workers whose worst deficit is 0 can never have one, and count 0.

`worker_deficits(constants, assignment)` gives each worker's $D_w$, and `rest_term(constants, worker, deficit)` one
worker's term.

### Helpers shared with the `incremental` module

`likes_total(constants, assignment)` and `workload_total(constants, assignment)` (the likes and workload penalties
before dividing by their units), `shift_likes_lower_bound(constants, shift, assignment, domains)` (one shift's share of the likes
look-ahead),
`pair_like_value(constants, worker, partner)` (both workers' like values of each other, from `pair_values`), `normalized_likes(constants,
total)`, `rest_deficit(constants, worker, earlier, later)` (one rest's deficit, its rest in available time),
`worker_deficits` and `rest_term` (above). Both modules use them, so that they do the
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

The assignment may already be partly filled, as with a history
([ADR 0031](../../decisions/0031-history-as-the-filled-part-of-one-schedule.md)): the totals of what's filled are
then computed from scratch, with `likes_total`, `workload_total` and `rest_penalty`, and kept up to date from there.

