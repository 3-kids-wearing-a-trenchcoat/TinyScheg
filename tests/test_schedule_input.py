"""Tests for tinyscheg.model.schedule_input."""
import datetime as dt

import pytest

from tinyscheg.model.schedule_input import (DEFAULT_LIKES_WEIGHT, DEFAULT_MIN_REST, DEFAULT_NEUTRAL_PARTNER,
                                            DEFAULT_REST_FACTOR, DEFAULT_REST_WEIGHT, DEFAULT_WORKLOAD_POWER,
                                            DEFAULT_WORKLOAD_WEIGHT, MAX_NEUTRAL_PARTNER, ScoringParameters,
                                            Settings)
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


# --- scoring parameters ---

def test_scoring_defaults() -> None:
    parameters = Settings(hours(0, 12)).scoring
    assert parameters == ScoringParameters()
    assert (parameters.likes_weight, parameters.workload_weight, parameters.rest_weight) == (
        DEFAULT_LIKES_WEIGHT, DEFAULT_WORKLOAD_WEIGHT, DEFAULT_REST_WEIGHT)
    assert parameters.workload_power == DEFAULT_WORKLOAD_POWER
    assert parameters.rest_factor == DEFAULT_REST_FACTOR
    assert parameters.neutral_partner == DEFAULT_NEUTRAL_PARTNER


def test_weights_are_relative() -> None:
    parameters = ScoringParameters(likes_weight=1, workload_weight=2, rest_weight=1)
    assert (parameters.likes_weight, parameters.workload_weight, parameters.rest_weight) == (0.25, 0.5, 0.25)
    assert parameters == ScoringParameters()


def test_a_zero_weight_is_allowed() -> None:
    assert ScoringParameters(likes_weight=0).likes_weight == 0


@pytest.mark.parametrize("overrides", [
    {"likes_weight": -1},
    {"likes_weight": 0, "workload_weight": 0, "rest_weight": 0},
    {"workload_power": 1},
    {"workload_power": 2.5},
    {"workload_power": True},
    {"rest_factor": 0.5},
    {"neutral_partner": 0},
    {"neutral_partner": 0.5},  # a dislike and a like would cancel out (ADR 0023)
    {"neutral_partner": 1},
    {"rest_factor": float("nan")},
    {"rest_weight": "high"},
])
def test_invalid_scoring_parameters(overrides: dict) -> None:
    with pytest.raises((TypeError, ValueError)):
        ScoringParameters(**overrides)


def test_a_dislike_must_outweigh_a_like() -> None:
    # at 1/2, a pair where one dislikes the other and the other likes them would cost as much as a neutral pair
    assert ScoringParameters(neutral_partner=0.49).neutral_partner == 0.49
    with pytest.raises(ValueError, match="disliking a partner counts more than liking one"):
        ScoringParameters(neutral_partner=MAX_NEUTRAL_PARTNER)
