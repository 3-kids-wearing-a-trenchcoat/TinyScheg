# `daily_window` module

Source: [`src/tinyscheg/timing/daily_window.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/timing/daily_window.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_daily_window.py`).

## `class DailyWindow(start, end)`

A time window that recurs every day, from `start` to `end` (both `datetime.time`, timezone-naive). Windows are
immutable and hashable.

* An `end` earlier than the `start` crosses midnight: `19:00-07:00` is 7 PM to 7 AM the next day.
* An `end` equal to the `start` covers the full 24 hours: `00:00-00:00`, or `06:00-06:00` (from 6 AM to 6 AM).

**Raises** `TypeError` if `start` or `end` isn't a `datetime.time`, and `ValueError` if either is timezone-aware.

`str(window)` gives the window as `"HH:MM-HH:MM"`.

### Methods and properties

| Member | Returns | Description |
|--------|---------|-------------|
| `parse(text)` (class method) | `DailyWindow` | Parses `"HH:MM-HH:MM"`. Hours are 0–23 (one or two digits) and minutes 0–59; surrounding spaces are ignored. Raises `TypeError` for a non-string and `ValueError` for anything else invalid, such as `"24:00-07:00"`. |
| `length` (property) | `datetime.timedelta` | The length of one occurrence: more than 0 and at most 24 hours. |
| `occurrences(period)` | `list[DateTimeRange]` | Every occurrence of the window within the [`DateTimeRange`](datetime-range.md) `period`, each cut to the period, in time order. Includes an occurrence that opened the day before the period and is still open when it starts. |
| `overlaps(other)` | `bool` | `True` if the two windows are ever open at the same time. Windows that only touch don't overlap. |

For example, over a period from January 1st 00:00 to January 2nd 12:00, `19:00-07:00` occurs from Jan 1st 00:00
to 07:00 (it opened on December 31st) and from Jan 1st 19:00 to Jan 2nd 07:00.
