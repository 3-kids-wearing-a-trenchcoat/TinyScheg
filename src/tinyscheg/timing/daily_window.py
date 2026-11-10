"""Recurring daily time windows, such as "19:00-07:00"."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from tinyscheg.timing.datetime_range import DateTimeRange

_WINDOW_PATTERN = re.compile(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})")
_ONE_DAY = dt.timedelta(days=1)


@dataclass(frozen=True, slots=True)
class DailyWindow:
    """
    A time window that recurs every day, from start to end.
    An end earlier than the start crosses midnight ("19:00-07:00" is 7 PM to 7 AM the next day), and an end equal to
    the start covers the full 24 hours ("00:00-00:00").
    """
    start: dt.time
    end: dt.time

    def __post_init__(self) -> None:
        """Validate the window's ends."""
        for name, value in (("start", self.start), ("end", self.end)):
            if not isinstance(value, dt.time):
                raise TypeError(f"{name} must be a datetime.time, not {type(value).__name__}")
            if value.tzinfo is not None:
                raise ValueError(f"{name} must be timezone-naive, got {value!r}")

    @classmethod
    def parse(cls, text: str) -> DailyWindow:
        """
        Parse a window written as "HH:MM-HH:MM"
        :param text: str, e.g. "19:00-07:00"; hours are 0-23 and minutes 0-59
        :return: the DailyWindow
        """
        if not isinstance(text, str):
            raise TypeError(f'expected a time window "HH:MM-HH:MM", got {text!r}')
        match = _WINDOW_PATTERN.fullmatch(text.strip())
        if match is None:
            raise ValueError(f'expected a time window "HH:MM-HH:MM", got {text!r}')
        start_hour, start_minute, end_hour, end_minute = (int(group) for group in match.groups())
        try:
            return cls(dt.time(start_hour, start_minute), dt.time(end_hour, end_minute))
        except ValueError as exc:  # hour or minute out of range
            raise ValueError(f"invalid time window {text!r}: {exc}") from exc

    def __str__(self) -> str:
        """The window as "HH:MM-HH:MM"."""
        return f"{self.start:%H:%M}-{self.end:%H:%M}"

    @property
    def length(self) -> dt.timedelta:
        """The length of one occurrence of the window: between just over 0 and 24 hours."""
        start = dt.datetime.combine(dt.date.min, self.start)
        end = dt.datetime.combine(dt.date.min, self.end)
        if end <= start:  # crosses midnight, or covers the full day
            end += _ONE_DAY
        return end - start

    def occurrences(self, period: DateTimeRange) -> list[DateTimeRange]:
        """
        Find every occurrence of the window that falls within a period
        :param period: DateTimeRange
        :return: the occurrences, each cut to the period, in time order. This includes an occurrence that opened the
        day before the period starts and is still open when it does.
        """
        result = []
        day = period.start.date() - _ONE_DAY
        while (opening := dt.datetime.combine(day, self.start)) < period.end:
            clipped = DateTimeRange.from_duration(opening, self.length).intersection(period)
            if clipped is not None:
                result.append(clipped)
            day += _ONE_DAY
        return result

    def overlaps(self, other: DailyWindow) -> bool:
        """True if the two windows are ever open at the same time."""
        # Both windows repeat daily and last at most a day, so if they ever overlap, they overlap within any period of
        # two whole days (occurrences that opened the day before are included).
        reference = DateTimeRange(dt.datetime(2000, 1, 2), dt.datetime(2000, 1, 4))
        return any(mine.overlaps(theirs)
                   for mine in self.occurrences(reference)
                   for theirs in other.occurrences(reference))
