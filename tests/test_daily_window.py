"""Tests for tinyscheg.timing.daily_window."""
import datetime as dt

import pytest

from tinyscheg.timing.daily_window import DailyWindow
from tinyscheg.timing.datetime_range import DateTimeRange


def at(day: int, hour: int, minute: int = 0) -> dt.datetime:
    """A datetime on 2025-01-<day> at hour:minute."""
    return dt.datetime(2025, 1, day, hour, minute)


# --- parsing ---

def test_parse() -> None:
    window = DailyWindow.parse("19:00-07:30")
    assert window == DailyWindow(dt.time(19, 0), dt.time(7, 30))
    assert str(window) == "19:00-07:30"


def test_parse_accepts_single_digit_hours_and_spaces() -> None:
    assert DailyWindow.parse(" 7:00-9:15 ") == DailyWindow(dt.time(7, 0), dt.time(9, 15))


@pytest.mark.parametrize("text", ["24:00-07:00", "19:60-07:00", "19:00", "19:00-07", "7pm-7am", ""])
def test_parse_rejects_invalid_text(text: str) -> None:
    with pytest.raises(ValueError):
        DailyWindow.parse(text)


def test_parse_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        DailyWindow.parse(1900)  # type: ignore[arg-type]


def test_rejects_non_time_ends() -> None:
    with pytest.raises(TypeError):
        DailyWindow("19:00", dt.time(7))  # type: ignore[arg-type]


# --- length ---

@pytest.mark.parametrize("text, hours", [
    ("08:00-20:00", 12),
    ("19:00-07:00", 12),   # crosses midnight
    ("00:00-00:00", 24),   # full day
    ("07:00-07:00", 24),
    ("23:00-00:00", 1),
])
def test_length(text: str, hours: int) -> None:
    assert DailyWindow.parse(text).length == dt.timedelta(hours=hours)


# --- occurrences ---

def test_occurrences_within_day() -> None:
    period = DateTimeRange(at(1, 0), at(3, 0))
    assert DailyWindow.parse("08:00-20:00").occurrences(period) == [
        DateTimeRange(at(1, 8), at(1, 20)),
        DateTimeRange(at(2, 8), at(2, 20)),
    ]


def test_occurrences_crossing_midnight_include_previous_day() -> None:
    period = DateTimeRange(at(1, 0), at(2, 12))
    assert DailyWindow.parse("19:00-07:00").occurrences(period) == [
        DateTimeRange(at(1, 0), at(1, 7)),     # opened on the day before the period, cut at its start
        DateTimeRange(at(1, 19), at(2, 7)),
    ]


def test_occurrences_are_cut_to_the_period() -> None:
    period = DateTimeRange(at(1, 10), at(2, 9))
    assert DailyWindow.parse("08:00-20:00").occurrences(period) == [
        DateTimeRange(at(1, 10), at(1, 20)),
        DateTimeRange(at(2, 8), at(2, 9)),
    ]


def test_occurrences_full_day_touch_at_the_window_edge() -> None:
    period = DateTimeRange(at(1, 0), at(3, 0))
    assert DailyWindow.parse("06:00-06:00").occurrences(period) == [
        DateTimeRange(at(1, 0), at(1, 6)),
        DateTimeRange(at(1, 6), at(2, 6)),
        DateTimeRange(at(2, 6), at(3, 0)),
    ]


def test_occurrences_none_in_period() -> None:
    period = DateTimeRange(at(1, 21), at(1, 23))
    assert DailyWindow.parse("08:00-20:00").occurrences(period) == []


def test_occurrence_ending_exactly_at_period_start_is_excluded() -> None:
    period = DateTimeRange(at(1, 7), at(1, 12))
    assert DailyWindow.parse("19:00-07:00").occurrences(period) == []


# --- overlaps ---

@pytest.mark.parametrize("first, second, expected", [
    ("08:00-12:00", "10:00-14:00", True),
    ("08:00-12:00", "12:00-14:00", False),  # touching
    ("19:00-07:00", "06:00-08:00", True),   # overlap after midnight
    ("19:00-07:00", "07:00-19:00", False),  # complementary
    ("22:00-02:00", "01:00-03:00", True),
    ("00:00-00:00", "03:00-04:00", True),   # a full day overlaps everything
    ("23:00-01:00", "01:00-23:00", False),
])
def test_overlaps(first: str, second: str, expected: bool) -> None:
    first_window, second_window = DailyWindow.parse(first), DailyWindow.parse(second)
    assert first_window.overlaps(second_window) is expected
    assert second_window.overlaps(first_window) is expected
