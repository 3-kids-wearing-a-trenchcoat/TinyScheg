# `schedule_input` module

Source: [`src/tinyscheg/model/schedule_input.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/schedule_input.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_schedule_input.py`).

The parsed input as a whole, as produced by [`read_input`](parsing.md#read_inputpath-read_historytrue). It lives in `model` so that
the CSP and output code can use it without depending on `parsing`.

## Constants

* `DEFAULT_MIN_REST` — `datetime.timedelta(hours=6)`, the minimum rest period when the input doesn't set one.
* Scoring parameter defaults ([ADR 0022](../../decisions/0022-scoring-parameters-with-defaults-and-input-overrides.md)):
  `DEFAULT_LIKES_WEIGHT = 0.25`, `DEFAULT_WORKLOAD_WEIGHT = 0.5`, `DEFAULT_REST_WEIGHT = 0.25`,
  `DEFAULT_WORKLOAD_POWER = 2`, `DEFAULT_REST_FACTOR = 2.5`, `DEFAULT_NEUTRAL_PARTNER = 1/3`,
  `DEFAULT_SHIFT_SHARE = 0.5`.
* Limits: `MIN_WORKLOAD_POWER = 2`, `MIN_REST_FACTOR = 1.0`.

## `class ScoringParameters(likes_weight, workload_weight, rest_weight, workload_power, rest_factor, neutral_partner, shift_share)`

The parameters of the [penalty score](../../explanation/scoring.md#parameters). Immutable; every field defaults to
its constant above.

* `likes_weight`, `workload_weight`, `rest_weight` — the weights $a$, $b$, $c$. Each at least 0, not all 0. They're
  **relative**: they're stored divided by their sum, so `ScoringParameters(1, 2, 1) == ScoringParameters()`.
* `workload_power` — $p$ in $\varphi(x) = x^p$, a whole number of at least `MIN_WORKLOAD_POWER`.
* `rest_factor` — $\gamma$, at least `MIN_REST_FACTOR`.
* `neutral_partner` — $\alpha / \beta$, more than 0 and less than `MAX_NEUTRAL_PARTNER` (1/2), so that a dislike
  outweighs a like ([ADR 0023](../../decisions/0023-dislikes-outweigh-likes.md)).
* `shift_share` — $\sigma$, from 0 to 1: how much a slot's load for the workload penalty counts it as one average
  slot rather than by its hours ([ADR 0026](../../decisions/0026-workload-counts-shifts-and-hours.md)).

**Raises** `TypeError` for a value that isn't a number (or, for `workload_power`, a whole number), and `ValueError`
for one out of range; the message names the parameter.

## `class Settings(period, min_rest=DEFAULT_MIN_REST, scoring=ScoringParameters())`

General scheduler settings. Immutable.

* `period` — [`DateTimeRange`](datetime-range.md), the time period to generate a schedule for.
* `min_rest` — `datetime.timedelta`, the minimum time between two shifts assigned to the same worker. May be 0.
* `scoring` — `ScoringParameters`.

**Raises** `ValueError` if `min_rest` is negative.

## `class ScheduleInput(settings, workers, posts, history=())`

Everything a schedule is made from. Immutable.

* `settings` — `Settings`.
* `workers` — the [`Worker`](worker.md)s, in input order; stored as a `tuple`.
* `posts` — the [`Post`](post-and-slot.md#class-postname-rules-windownone-variations)s, in input order; stored as a
  `tuple`.
* `history` — the `PreviousSchedule`s this schedule extends, in input order; stored as a `tuple`
  ([ADR 0029](../../decisions/0029-schedule-history-input.md)).

## `class PreviousSchedule(source, schedule_input, assignment)`

A previous schedule, as fixed history. Immutable.

* `source` — the input file's path as the history lists it, for messages.
* `schedule_input` — the `ScheduleInput` it was made for. Its own `history` is always empty: it's never read.
* `assignment` — `tuple[int, ...]`, a worker index into `schedule_input.workers` for each slot of the shifts
  generated from `schedule_input`, in stable slot order.

Input order matters: it's part of the stable order that keeps results deterministic
([ADR 0012](../../decisions/0012-deterministic-path-independent-scoring.md)).
