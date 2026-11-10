# `schedule_input` module

Source: [`src/tinyscheg/model/schedule_input.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/model/schedule_input.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_schedule_input.py`).

The parsed input as a whole, as produced by [`read_input`](parsing.md#read_inputpath). It lives in `model` so that
the CSP and output code can use it without depending on `parsing`.

## Constants

`DEFAULT_MIN_REST` — `datetime.timedelta(hours=6)`, the minimum rest period when the input doesn't set one.

## `class Settings(period, min_rest=DEFAULT_MIN_REST)`

General scheduler settings. Immutable.

* `period` — [`DateTimeRange`](datetime-range.md), the time period to generate a schedule for.
* `min_rest` — `datetime.timedelta`, the minimum time between two shifts assigned to the same worker. May be 0.

**Raises** `ValueError` if `min_rest` is negative.

## `class ScheduleInput(settings, workers, posts)`

Everything a schedule is made from. Immutable.

* `settings` — `Settings`.
* `workers` — the [`Worker`](worker.md)s, in input order; stored as a `tuple`.
* `posts` — the [`Post`](post-and-slot.md#class-postname-rules-windownone-variations)s, in input order; stored as a
  `tuple`.

Input order matters: it's part of the stable order that keeps results deterministic
([ADR 0012](../../decisions/0012-deterministic-path-independent-scoring.md)).
