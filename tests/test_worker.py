"""Tests for tinyscheg.model.worker."""
import datetime as dt

import pytest

from tinyscheg.model.worker import Worker
from tinyscheg.timing.datetime_range import DateTimeRange


def hours(start: int, end: int) -> DateTimeRange:
    """The range from start:00 to end:00 on 2025-01-01."""
    return DateTimeRange(dt.datetime(2025, 1, 1, start), dt.datetime(2025, 1, 1, end))


def test_worker_defaults_are_empty() -> None:
    worker = Worker("Anne")
    assert worker.roles == frozenset()
    assert worker.unavailable == ()
    assert worker.likes == frozenset()
    assert worker.dislikes == frozenset()


def test_worker_canonicalizes_collections() -> None:
    worker = Worker("Jack", roles=["supervisor"], unavailable=[hours(8, 9), hours(1, 2)],  # type: ignore[arg-type]
                    likes=["Jill"])  # type: ignore[arg-type]
    assert worker.roles == frozenset({"supervisor"})
    assert worker.unavailable == (hours(1, 2), hours(8, 9))
    assert worker.likes == frozenset({"Jill"})
    hash(worker)  # immutable and hashable


def test_worker_has_role() -> None:
    worker = Worker("Jack", roles=frozenset({"supervisor"}))
    assert worker.has_role("supervisor")
    assert worker.has_role("any")
    assert not worker.has_role("security")
    assert Worker("Anne").has_role("any")


@pytest.mark.parametrize("time_range, expected", [
    (hours(2, 4), True),    # ends as the unavailability starts
    (hours(3, 5), False),
    (hours(5, 6), False),   # inside
    (hours(6, 8), True),    # starts as the unavailability ends
])
def test_worker_is_available(time_range: DateTimeRange, expected: bool) -> None:
    assert Worker("Jack", unavailable=(hours(4, 6),)).is_available(time_range) is expected


def test_worker_likes_and_dislikes_by_name() -> None:
    jack = Worker("Jack", likes=frozenset({"Jill"}), dislikes=frozenset({"Jeff"}))
    assert jack.likes_worker(Worker("Jill"))
    assert not jack.likes_worker(Worker("Jeff"))
    assert jack.dislikes_worker(Worker("Jeff"))
    assert not jack.dislikes_worker(Worker("Anne"))
