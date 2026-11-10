# `datetime_range` module

Source: [`src/tinyscheg/timing/datetime_range.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/timing/datetime_range.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_datetime_range.py`).

## `class DateTimeRange(start, end)`

A non-empty date-time range `[start, end)`: the start is included and the end isn't. Every method follows this
convention. Both ends are timezone-naive `datetime.datetime` objects (timezones are not taken into account), and
`start < end`.

Ranges are immutable: their ends can't be changed after creation.

**Parameters**

* `start` — `datetime.datetime`, the start of the range.
* `end` — `datetime.datetime`, the end of the range.

**Raises**

* `TypeError` if `start` or `end` isn't a `datetime.datetime` (a `datetime.date` isn't accepted).
* `ValueError` if either is timezone-aware, or if `start` isn't before `end`.

### Attributes and properties

| Name       | Type                 | Description          |
|------------|----------------------|----------------------|
| `start`    | `datetime.datetime`  | Start of the range (included). |
| `end`      | `datetime.datetime`  | End of the range (excluded). |
| `duration` | `datetime.timedelta` | `end - start` (read-only property). |

### Comparison and hashing

* `==` — two ranges are equal if both their starts and ends are equal.
* `<`, `<=`, `>`, `>=` — ranges are ordered by `(start, end)`: first by start, then by end.
* Ranges are hashable, so they can be used as dictionary keys and set members.

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `from_duration(start, length)` (class method) | `DateTimeRange` | The range `[start, start + length)`. Raises `TypeError` if `length` isn't a `datetime.timedelta`, and `ValueError` if it isn't positive. |
| `contains(other)` | `bool` | `True` if `other` lies entirely within this range. `other` is a `datetime.datetime` (a moment: `start <= other < end`) or a `DateTimeRange` (`start <= other.start` and `other.end <= end`). Raises `TypeError` for anything else. |
| `overlaps(other)` | `bool` | `True` if the two ranges share some time. Ranges that only touch, one ending exactly as the other starts, don't overlap. |
| `intersection(other)` | `DateTimeRange \| None` | The range contained in both ranges, or `None` if they don't overlap. |
| `gap(other)` | `datetime.timedelta` | The time from the end of the earlier range to the start of the later one, in either order; zero if the ranges touch or overlap. |

`overlaps`, `intersection` and `gap` are symmetric: `a.gap(b) == b.gap(a)`, and so on.

Two slots get a [difference constraint](../../explanation/csp-formulation.md#binary-difference-constraints) exactly
when `a.overlaps(b) or a.gap(b) < min_rest`.

## `parse_range(str_pair)`

Transforms a pair of ISO 8601 date-time strings into a `DateTimeRange`. A date without a time is taken to be
midnight, so `["2025-01-03", "2025-01-04"]` is the whole of January 3rd.

**Parameters**

* `str_pair` — a list or tuple of two strings, `(start, end)`.

**Returns** a `DateTimeRange` from `start` to `end`.

**Raises**

* `TypeError` if the input isn't a list or tuple of exactly two strings.
* `ValueError` if either string can't be parsed by `datetime.datetime.fromisoformat` (the message names the
  string), or if the resulting range is invalid (e.g. `start` isn't before `end`).
