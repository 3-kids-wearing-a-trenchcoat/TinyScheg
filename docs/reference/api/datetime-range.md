# `DateTimeRange` module

Source: [`src/DateTimeRange.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/DateTimeRange.py)

> [!NOTE]
> **Implemented.**

## `class DateTimeRange(start, end)`

A simple date-time range `[start, end)`: the start is inclusive and the end is exclusive.
Both ends are timezone-naive `datetime.datetime` objects (timezones are not taken into account) and
`start <= end`.

**Parameters**

* `start` — `datetime.datetime`, the start of the range.
* `end` — either a `datetime.datetime` representing the end of the range, or a `datetime.timedelta` representing
  the length of the range from `start`.

**Raises**

* `TypeError` if `start` is not a `datetime.datetime`, or `end` is neither a `datetime.datetime` nor a
  `datetime.timedelta`.
* `ValueError` if `start` is after `end`.

### Attributes and properties

| Name       | Type                 | Description          |
|------------|----------------------|----------------------|
| `start`    | `datetime.datetime`  | Start of the range.  |
| `end`      | `datetime.datetime`  | End of the range.    |
| `duration` | `datetime.timedelta` | `end - start` (read-only property). |

### Comparison and hashing

* `==` — two ranges are equal if both their starts and ends are equal.
* `<`, `<=`, `>`, `>=` — ranges are ordered by `(start, end)`: first by start, then by end.
* Ranges are hashable (by `(start, end)`), so they can be used as dictionary keys and set members.

Comparing with anything other than a `DateTimeRange` returns `NotImplemented`.

### Methods

| Method                | Returns              | Description |
|-----------------------|----------------------|-------------|
| `touches(other)`      | `bool`               | `True` if one range starts exactly when the other ends. |
| `overlaps(other)`     | `bool`               | `True` if the two ranges share some period of time. Ranges that only touch don't overlap. |
| `in_range(other)`     | `bool`               | `True` if `other` is entirely contained within this range. `other` may be a `DateTimeRange` or a `datetime.datetime`. |
| `is_before(other)`    | `bool`               | `True` if this range ends before `other` (a `DateTimeRange` or a `datetime.datetime`) begins. |
| `is_after(other)`     | `bool`               | `True` if this range begins after `other` (a `DateTimeRange` or a `datetime.datetime`) ends. |
| `intersect(other)`    | `DateTimeRange \| None` | The range contained within both this range and `other`, or `None` if they don't overlap. |
| `pad(padding)`        | `DateTimeRange \| None` | Pads the range by the `datetime.timedelta` `padding`, returning `[start + padding, end + padding)`. Returns `None` if applying a (negative) padding results in `start >= end`. |
| `time_str()`          | `str`                | The range's start and end times of day, as a string. |
| `forever()` (static)  | `DateTimeRange`      | A range spanning `datetime.datetime.min` to `datetime.datetime.max`. Used as the activity period of posts that are always active. |

## `parse_range(str_pair)`

Transforms a pair of ISO 8601 date-time strings into a `DateTimeRange`. A date without a time is taken to be
midnight.

**Parameters**

* `str_pair` — a pair (tuple or list) of two strings, `(start, end)`.

**Returns** a `DateTimeRange` from `start` to `end`.

**Raises**

* `TypeError` if the input is anything other than a pair of strings.
* `ValueError` if either string can't be parsed by `datetime.datetime.fromisoformat`.
