"""Tests for tinyscheg.timing.datetime_range."""
import datetime as dt

import pytest

from tinyscheg.timing.datetime_range import DateTimeRange, parse_range


def at(hour: int, minute: int = 0, day: int = 1) -> dt.datetime:
    """A datetime on 2025-01-<day> at hour:minute."""
    return dt.datetime(2025, 1, day, hour, minute)


def hours(start: int, end: int) -> DateTimeRange:
    """The range from start:00 to end:00 on 2025-01-01."""
    return DateTimeRange(at(start), at(end))


# --- construction ---

def test_construction_keeps_ends() -> None:
    time_range = hours(3, 5)
    assert time_range.start == at(3)
    assert time_range.end == at(5)
    assert time_range.duration == dt.timedelta(hours=2)


@pytest.mark.parametrize("start, end", [(at(5), at(5)), (at(5), at(3))])
def test_construction_rejects_empty_or_reversed(start: dt.datetime, end: dt.datetime) -> None:
    with pytest.raises(ValueError):
        DateTimeRange(start, end)


@pytest.mark.parametrize("start, end", [
    ("2025-01-01", at(5)),
    (at(3), dt.timedelta(hours=2)),
    (dt.date(2025, 1, 1), at(5)),
])
def test_construction_rejects_wrong_types(start: object, end: object) -> None:
    with pytest.raises(TypeError):
        DateTimeRange(start, end)  # type: ignore[arg-type]


def test_construction_rejects_timezone_aware() -> None:
    aware = dt.datetime(2025, 1, 1, 5, tzinfo=dt.timezone.utc)
    with pytest.raises(ValueError):
        DateTimeRange(at(3), aware)


def test_is_immutable() -> None:
    time_range = hours(3, 5)
    with pytest.raises(AttributeError):
        time_range.start = at(1)  # type: ignore[misc]


def test_from_duration() -> None:
    assert DateTimeRange.from_duration(at(3), dt.timedelta(hours=2)) == hours(3, 5)


@pytest.mark.parametrize("length", [dt.timedelta(0), dt.timedelta(hours=-1)])
def test_from_duration_rejects_non_positive_length(length: dt.timedelta) -> None:
    with pytest.raises(ValueError):
        DateTimeRange.from_duration(at(3), length)


def test_from_duration_rejects_wrong_type() -> None:
    with pytest.raises(TypeError):
        DateTimeRange.from_duration(at(3), 2)  # type: ignore[arg-type]


# --- ordering and hashing ---

def test_ordering_by_start_then_end() -> None:
    assert hours(1, 5) < hours(2, 3)
    assert hours(1, 3) < hours(1, 5)
    assert sorted([hours(2, 3), hours(1, 5), hours(1, 3)]) == [hours(1, 3), hours(1, 5), hours(2, 3)]


def test_equal_ranges_hash_equally() -> None:
    assert hours(1, 3) == hours(1, 3)
    assert len({hours(1, 3), hours(1, 3), hours(1, 4)}) == 2


# --- contains ---

@pytest.mark.parametrize("moment, expected", [
    (at(3), True),        # start is included
    (at(4, 59), True),
    (at(5), False),       # end is excluded
    (at(2, 59), False),
])
def test_contains_moment(moment: dt.datetime, expected: bool) -> None:
    assert hours(3, 5).contains(moment) is expected


@pytest.mark.parametrize("other, expected", [
    (hours(3, 5), True),  # same range
    (hours(3, 4), True),  # shares the start
    (hours(4, 5), True),  # shares the end
    (hours(2, 4), False),
    (hours(4, 6), False),
    (hours(1, 7), False),
])
def test_contains_range(other: DateTimeRange, expected: bool) -> None:
    assert hours(3, 5).contains(other) is expected


def test_contains_rejects_wrong_type() -> None:
    with pytest.raises(TypeError):
        hours(3, 5).contains("04:00")  # type: ignore[arg-type]


# --- overlaps, intersection, gap ---

@pytest.mark.parametrize("other, overlaps, intersection, gap_hours", [
    (hours(4, 7), True, hours(4, 5), 0),    # partial overlap
    (hours(1, 4), True, hours(3, 4), 0),    # partial overlap, other first
    (hours(3, 5), True, hours(3, 5), 0),    # equal
    (hours(1, 7), True, hours(3, 5), 0),    # other contains self
    (hours(5, 7), False, None, 0),          # touch: self ends as other starts
    (hours(1, 3), False, None, 0),          # touch: other ends as self starts
    (hours(8, 9), False, None, 3),          # disjoint, other after
    (hours(0, 1), False, None, 2),          # disjoint, other before
])
def test_overlaps_intersection_gap(other: DateTimeRange, overlaps: bool, intersection: DateTimeRange | None,
                                   gap_hours: int) -> None:
    this = hours(3, 5)
    # every relation is symmetric
    for first, second in ((this, other), (other, this)):
        assert first.overlaps(second) is overlaps
        assert first.intersection(second) == intersection
        assert first.gap(second) == dt.timedelta(hours=gap_hours)


# --- parse_range ---

def test_parse_range_full_date_times() -> None:
    assert parse_range(["2025-01-01T03:00:00", "2025-01-01T05:00:00"]) == hours(3, 5)


def test_parse_range_date_only_is_midnight() -> None:
    parsed = parse_range(("2025-01-03", "2025-01-04"))
    assert parsed == DateTimeRange(dt.datetime(2025, 1, 3), dt.datetime(2025, 1, 4))


def test_parse_range_bad_string_names_it() -> None:
    with pytest.raises(ValueError, match="not-a-date"):
        parse_range(["2025-01-01", "not-a-date"])


def test_parse_range_reversed_is_value_error() -> None:
    with pytest.raises(ValueError):
        parse_range(["2025-01-04", "2025-01-03"])


@pytest.mark.parametrize("value", [
    "ab",                                   # a string is a sequence of two characters, but not a pair
    ["2025-01-01"],
    ["2025-01-01", "2025-01-02", "2025-01-03"],
    ["2025-01-01", None],
    None,
])
def test_parse_range_rejects_wrong_shapes(value: object) -> None:
    with pytest.raises(TypeError):
        parse_range(value)  # type: ignore[arg-type]
