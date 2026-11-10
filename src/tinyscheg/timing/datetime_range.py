"""Half-open date-time ranges, and parsing them from ISO 8601 strings."""
from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class DateTimeRange:
    """
    A non-empty date-time range [start, end): the start is included and the end isn't.
    Both ends are timezone-naive datetime.datetime objects, and start < end.
    Ranges are immutable, hashable, and ordered by (start, end).
    """
    start: dt.datetime
    end: dt.datetime

    def __post_init__(self) -> None:
        """Validate the range's ends."""
        for name, value in (("start", self.start), ("end", self.end)):
            if not isinstance(value, dt.datetime):
                raise TypeError(f"{name} must be a datetime.datetime, not {type(value).__name__}")
            if value.tzinfo is not None:
                raise ValueError(f"{name} must be timezone-naive, got {value!r}")
        if self.start >= self.end:
            raise ValueError(f"start must be before end, got {self.start.isoformat()} -> {self.end.isoformat()}")

    @classmethod
    def from_duration(cls, start: dt.datetime, length: dt.timedelta) -> DateTimeRange:
        """
        Create a range from its start and its length
        :param start: datetime.datetime, the start of the range
        :param length: datetime.timedelta, the length of the range; must be positive
        :return: the range [start, start + length)
        """
        if not isinstance(length, dt.timedelta):
            raise TypeError(f"length must be a datetime.timedelta, not {type(length).__name__}")
        return cls(start, start + length)

    @property
    def duration(self) -> dt.timedelta:
        """The length of the range, end - start."""
        return self.end - self.start

    def contains(self, other: dt.datetime | DateTimeRange) -> bool:
        """
        Check whether a moment or a range lies entirely within this range
        :param other: datetime.datetime (a moment) or DateTimeRange
        :return: True if other is within this range. A range ending exactly at this range's end is within it,
        but a moment exactly at this range's end isn't, since the end is excluded.
        """
        if isinstance(other, DateTimeRange):
            return self.start <= other.start and other.end <= self.end
        if isinstance(other, dt.datetime):
            return self.start <= other < self.end
        raise TypeError(f"other must be a datetime.datetime or a DateTimeRange, not {type(other).__name__}")

    def overlaps(self, other: DateTimeRange) -> bool:
        """True if the two ranges share some time. Ranges that only touch (one ends as the other starts) don't."""
        return self.start < other.end and other.start < self.end

    def intersection(self, other: DateTimeRange) -> DateTimeRange | None:
        """
        Find the time shared by two ranges
        :param other: DateTimeRange
        :return: the range contained in both ranges, or None if they don't overlap
        """
        if not self.overlaps(other):
            return None
        return DateTimeRange(max(self.start, other.start), min(self.end, other.end))

    def gap(self, other: DateTimeRange) -> dt.timedelta:
        """
        Find the time between two ranges, in either order
        :param other: DateTimeRange
        :return: datetime.timedelta from the end of the earlier range to the start of the later one, or zero if
        the ranges touch or overlap
        """
        return max(other.start - self.end, self.start - other.end, dt.timedelta(0))


def parse_range(str_pair: Sequence[str]) -> DateTimeRange:
    """
    Transform a pair of ISO 8601 date-time strings into a DateTimeRange.
    A date without a time is taken to be midnight.
    :param str_pair: list or tuple of two strings, (start, end)
    :return: DateTimeRange from start to end
    """
    if not isinstance(str_pair, (list, tuple)) or len(str_pair) != 2 \
            or not all(isinstance(item, str) for item in str_pair):
        raise TypeError(f"expected a pair of strings, got {str_pair!r}")
    start, end = (_parse_datetime(item) for item in str_pair)
    return DateTimeRange(start, end)


def _parse_datetime(text: str) -> dt.datetime:
    """Parse one ISO 8601 date-time string, raising a ValueError that names the string if it can't be parsed."""
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"could not parse date-time {text!r}: {exc}") from exc
