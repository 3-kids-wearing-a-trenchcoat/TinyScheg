"""Tests for tinyscheg.model.post."""
import datetime as dt

import pytest

from tinyscheg.model.post import Post, ShiftRules, Variation
from tinyscheg.timing.daily_window import DailyWindow


def test_shift_rules_keep_role_order_and_count_workers() -> None:
    rules = ShiftRules(dt.timedelta(hours=3), (("security", 1), ("any", 2)))
    assert rules.roles == (("security", 1), ("any", 2))
    assert rules.workers_needed == 3


def test_shift_rules_allow_no_workers() -> None:
    assert ShiftRules(dt.timedelta(hours=3), ()).workers_needed == 0


@pytest.mark.parametrize("length, roles", [
    (dt.timedelta(0), (("any", 1),)),
    (dt.timedelta(hours=-1), (("any", 1),)),
    (dt.timedelta(hours=3), (("any", -1),)),
    (dt.timedelta(hours=3), (("any", 1.5),)),
    (dt.timedelta(hours=3), (("any", True),)),
    (dt.timedelta(hours=3), (("any", 1), ("any", 2))),
])
def test_shift_rules_reject_invalid(length: dt.timedelta, roles: tuple[tuple[str, int], ...]) -> None:
    with pytest.raises(ValueError):
        ShiftRules(length, roles)


def test_post_defaults() -> None:
    post = Post("desk", ShiftRules(dt.timedelta(hours=4), (("supervisor", 1),)))
    assert post.window is None
    assert post.variations == ()


def test_post_with_variations_is_hashable() -> None:
    night = Variation(DailyWindow.parse("19:00-07:00"), ShiftRules(dt.timedelta(hours=3), (("any", 2),)))
    post = Post("front gate", ShiftRules(dt.timedelta(hours=3), (("any", 1),)), None, [night])  # type: ignore[arg-type]
    assert post.variations == (night,)
    hash(post)
