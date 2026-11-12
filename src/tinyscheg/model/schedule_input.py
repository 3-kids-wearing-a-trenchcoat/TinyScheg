"""The parsed input as a whole: settings, workers and posts."""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from tinyscheg.model.post import Post
from tinyscheg.model.worker import Worker
from tinyscheg.timing.datetime_range import DateTimeRange

DEFAULT_MIN_REST = dt.timedelta(hours=6)

# Scoring parameter defaults (ADR 0022). Weights are relative: they're divided by their sum. With the flat penalty
# (ADR 0032) they're set so that, on the tuning inputs, one event of each kind costs what it did before.
DEFAULT_LIKES_WEIGHT = 0.57
DEFAULT_WORKLOAD_WEIGHT = 0.215
DEFAULT_REST_WEIGHT = 0.215
DEFAULT_WORKLOAD_POWER = 2       # phi(x) = x ** p (ADR 0021)
DEFAULT_REST_FACTOR = 2.5        # gamma: the rest target after a shift is this many times its length
DEFAULT_NEUTRAL_PARTNER = 1 / 3  # alpha / beta: a neutral shift partner's penalty relative to a disliked one's
DEFAULT_SHIFT_SHARE = 0.5        # sigma: how much a shift's load counts it as a shift, rather than by its hours

# Limits on the scoring parameters
MIN_WORKLOAD_POWER = 2  # phi must be strictly convex
MIN_REST_FACTOR = 1.0   # a rest target shorter than the shift itself isn't meaningful
MAX_NEUTRAL_PARTNER = 0.5  # exclusive: below it, a dislike outweighs a like (ADR 0023); at it, they'd cancel out


@dataclass(frozen=True, slots=True)
class ScoringParameters:
    """
    The parameters of the penalty score (see docs/explanation/scoring.md#parameters).
    The weights are stored divided by their sum, so they always add up to 1.
    """
    likes_weight: float = DEFAULT_LIKES_WEIGHT
    workload_weight: float = DEFAULT_WORKLOAD_WEIGHT
    rest_weight: float = DEFAULT_REST_WEIGHT
    workload_power: int = DEFAULT_WORKLOAD_POWER
    rest_factor: float = DEFAULT_REST_FACTOR
    neutral_partner: float = DEFAULT_NEUTRAL_PARTNER
    shift_share: float = DEFAULT_SHIFT_SHARE

    def __post_init__(self) -> None:
        """Validate the parameters and normalize the weights."""
        weights = {"likes": self.likes_weight, "workload": self.workload_weight, "rest": self.rest_weight}
        for name, weight in weights.items():
            _check_number(f"the {name} weight", weight)
            if weight < 0:
                raise ValueError(f"the {name} weight must be at least 0, got {weight!r}")
        total = sum(weights.values())
        if total == 0:
            raise ValueError("the weights must not all be 0")
        object.__setattr__(self, "likes_weight", self.likes_weight / total)
        object.__setattr__(self, "workload_weight", self.workload_weight / total)
        object.__setattr__(self, "rest_weight", self.rest_weight / total)

        power = self.workload_power
        if isinstance(power, bool) or not isinstance(power, int) or power < MIN_WORKLOAD_POWER:
            raise ValueError(f"workload_power must be a whole number of at least {MIN_WORKLOAD_POWER}, got {power!r}")
        _check_number("rest_factor", self.rest_factor)
        if self.rest_factor < MIN_REST_FACTOR:
            raise ValueError(f"rest_factor must be at least {MIN_REST_FACTOR:g}, got {self.rest_factor!r}")
        _check_number("neutral_partner", self.neutral_partner)
        if not 0 < self.neutral_partner < MAX_NEUTRAL_PARTNER:
            raise ValueError(f"neutral_partner must be more than 0 and less than {MAX_NEUTRAL_PARTNER:g}, so that "
                             f"disliking a partner counts more than liking one; got {self.neutral_partner!r}")
        _check_number("shift_share", self.shift_share)
        if not 0 <= self.shift_share <= 1:
            raise ValueError(f"shift_share must be from 0 to 1, got {self.shift_share!r}")


def _check_number(name: str, value: object) -> None:
    """Raise TypeError unless value is a finite int or float (bool doesn't count)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TypeError(f"{name} must be a number, got {value!r}")


@dataclass(frozen=True, slots=True)
class Settings:
    """
    General scheduler settings: the period to schedule, the minimum rest between a worker's shifts, and the scoring
    parameters.
    """
    period: DateTimeRange
    min_rest: dt.timedelta = DEFAULT_MIN_REST
    scoring: ScoringParameters = field(default_factory=ScoringParameters)

    def __post_init__(self) -> None:
        """Validate the settings."""
        if self.min_rest < dt.timedelta(0):
            raise ValueError(f"min_rest must not be negative, got {self.min_rest}")


@dataclass(frozen=True, slots=True)
class ScheduleInput:
    """
    Everything a schedule is made from. Workers and posts keep their input order; history holds the previous
    schedules it extends (ADR 0029), in input order.
    """
    settings: Settings
    workers: tuple[Worker, ...]
    posts: tuple[Post, ...]
    history: tuple[PreviousSchedule, ...] = ()

    def __post_init__(self) -> None:
        """Store workers, posts and history as tuples."""
        object.__setattr__(self, "workers", tuple(self.workers))
        object.__setattr__(self, "posts", tuple(self.posts))
        object.__setattr__(self, "history", tuple(self.history))


@dataclass(frozen=True, slots=True)
class PreviousSchedule:
    """
    A previous schedule, as fixed history (ADR 0029): the input it was made for (whose own history is never read),
    and a worker index into that input's workers for each slot of its shifts, in stable slot order. source names
    the files it was read from, for messages.
    """
    source: str
    schedule_input: ScheduleInput
    assignment: tuple[int, ...]
