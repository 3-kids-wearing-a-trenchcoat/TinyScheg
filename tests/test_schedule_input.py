"""Tests for tinyscheg.model.schedule_input."""
import datetime as dt

import pytest

from tinyscheg.model.schedule_input import DEFAULT_MIN_REST, Settings
from tinyscheg.timing.datetime_range import DateTimeRange


def hours(start: int, end: int) -> DateTimeRange:
    """The range from start:00 to end:00 on 2025-01-01."""
    return DateTimeRange(dt.datetime(2025, 1, 1, start), dt.datetime(2025, 1, 1, end))


def test_settings_default_min_rest() -> None:
    assert Settings(hours(0, 12)).min_rest == DEFAULT_MIN_REST == dt.timedelta(hours=6)


def test_settings_allow_zero_min_rest() -> None:
    assert Settings(hours(0, 12), dt.timedelta(0)).min_rest == dt.timedelta(0)


def test_settings_reject_negative_min_rest() -> None:
    with pytest.raises(ValueError):
        Settings(hours(0, 12), dt.timedelta(hours=-1))
