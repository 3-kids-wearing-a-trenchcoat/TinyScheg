"""The parsed input as a whole: settings, workers and posts."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from tinyscheg.model.post import Post
from tinyscheg.model.worker import Worker
from tinyscheg.timing.datetime_range import DateTimeRange

DEFAULT_MIN_REST = dt.timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class Settings:
    """General scheduler settings: the period to schedule, and the minimum rest between a worker's shifts."""
    period: DateTimeRange
    min_rest: dt.timedelta = DEFAULT_MIN_REST

    def __post_init__(self) -> None:
        """Validate the settings."""
        if self.min_rest < dt.timedelta(0):
            raise ValueError(f"min_rest must not be negative, got {self.min_rest}")


@dataclass(frozen=True, slots=True)
class ScheduleInput:
    """Everything a schedule is made from. Workers and posts keep their input order."""
    settings: Settings
    workers: tuple[Worker, ...]
    posts: tuple[Post, ...]

    def __post_init__(self) -> None:
        """Store workers and posts as tuples."""
        object.__setattr__(self, "workers", tuple(self.workers))
        object.__setattr__(self, "posts", tuple(self.posts))
