"""Tests for tinyscheg.parsing.validation."""
import datetime as dt

import pytest

from tinyscheg.model.post import Post, ShiftRules, Variation
from tinyscheg.model.schedule_input import ScheduleInput, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.validation import InputError, find_problems, location, validate
from tinyscheg.timing.daily_window import DailyWindow
from tinyscheg.timing.datetime_range import DateTimeRange

SETTINGS = Settings(DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 2)))
RULES = ShiftRules(dt.timedelta(hours=3), (("any", 1),))


def post(name: str = "desk", *windows: str) -> Post:
    """A post with one variation per given window."""
    return Post(name, RULES, None, tuple(Variation(DailyWindow.parse(window), RULES) for window in windows))


def schedule(workers: list[Worker], posts: list[Post] | None = None) -> ScheduleInput:
    """A ScheduleInput with the given workers and posts."""
    return ScheduleInput(SETTINGS, tuple(workers), tuple(posts or [post()]))


def test_valid_input_has_no_problems() -> None:
    valid = schedule([Worker("Jack", likes=frozenset({"Jill"})), Worker("Jill", dislikes=frozenset({"Jack"}))],
                     [post("gate", "19:00-07:00", "07:00-12:00"), post("desk")])
    assert find_problems(valid) == []
    validate(valid)


def test_location() -> None:
    assert location("worker", 2, "Jeff") == 'worker #3 ("Jeff")'
    assert location("worker", 0) == "worker #1"


def test_duplicate_worker_names() -> None:
    problems = find_problems(schedule([Worker("Jack"), Worker("Jill"), Worker("Jack")]))
    assert problems == ['worker name "Jack" is used 2 times; names must be unique']


def test_duplicate_post_names() -> None:
    problems = find_problems(schedule([Worker("Jack")], [post("desk"), post("desk")]))
    assert problems == ['post name "desk" is used 2 times; names must be unique']


def test_name_separator_in_worker_name() -> None:
    problems = find_problems(schedule([Worker("Tom & Jerry")]))
    assert len(problems) == 1 and "Tom & Jerry" in problems[0] and "must not contain" in problems[0]


def test_unknown_liked_and_disliked_workers() -> None:
    problems = find_problems(schedule([Worker("Jack", likes=frozenset({"Jil"}), dislikes=frozenset({"Bob"})),
                                       Worker("Jill")]))
    assert problems == ['worker #1 ("Jack"), likes: unknown worker "Jil"',
                        'worker #1 ("Jack"), dislikes: unknown worker "Bob"']


def test_worker_listing_themselves() -> None:
    problems = find_problems(schedule([Worker("Jack", dislikes=frozenset({"Jack"}))]))
    assert problems == ['worker #1 ("Jack"), dislikes: a worker can\'t list themselves']


def test_worker_both_liked_and_disliked() -> None:
    problems = find_problems(schedule([Worker("Jack", likes=frozenset({"Jill"}), dislikes=frozenset({"Jill"})),
                                       Worker("Jill")]))
    assert problems == ['worker #1 ("Jack"): "Jill" is in both likes and dislikes']


def test_overlapping_variations() -> None:
    problems = find_problems(schedule([Worker("Jack")], [post("gate", "19:00-07:00", "06:00-08:00")]))
    assert problems == ['post #1 ("gate"): variation #1 (19:00-07:00) and variation #2 (06:00-08:00) overlap']


def test_all_problems_are_reported_together() -> None:
    invalid = schedule([Worker("Jack", likes=frozenset({"Nobody"})), Worker("Jack")],
                       [post("gate", "00:00-00:00", "03:00-04:00")])
    with pytest.raises(InputError) as caught:
        validate(invalid)
    assert len(caught.value.problems) == 3
    assert "Nobody" in str(caught.value)
