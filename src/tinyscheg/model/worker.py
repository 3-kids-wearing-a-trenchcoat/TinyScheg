"""Workers: the people assigned to slots."""
from __future__ import annotations

from dataclasses import dataclass

from tinyscheg.timing.datetime_range import DateTimeRange

ANY_ROLE = "any"
"""The wildcard role: every worker has it, including workers with no roles."""

NAME_SEPARATOR = " & "
"""Joins the names of workers sharing a cell in the output grid, so worker names must not contain it."""


@dataclass(frozen=True, slots=True)
class Worker:
    """
    A worker who can be assigned to slots. Workers are immutable, and hold no scoring or search state.
    likes and dislikes are names of other workers.
    """
    name: str
    roles: frozenset[str] = frozenset()
    unavailable: tuple[DateTimeRange, ...] = ()
    likes: frozenset[str] = frozenset()
    dislikes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Store the collections in their canonical forms, keeping unavailability sorted by time."""
        # frozen dataclasses can only set their fields through object.__setattr__
        object.__setattr__(self, "roles", frozenset(self.roles))
        object.__setattr__(self, "unavailable", tuple(sorted(self.unavailable)))
        object.__setattr__(self, "likes", frozenset(self.likes))
        object.__setattr__(self, "dislikes", frozenset(self.dislikes))

    def has_role(self, role: str) -> bool:
        """True if the worker has the role. Every worker has the wildcard role "any"."""
        return role == ANY_ROLE or role in self.roles

    def is_available(self, time_range: DateTimeRange) -> bool:
        """True if the time range doesn't overlap any of the worker's unavailability."""
        return not any(unavailable.overlaps(time_range) for unavailable in self.unavailable)

    def likes_worker(self, other: Worker) -> bool:
        """True if this worker likes sharing a shift with other."""
        return other.name in self.likes

    def dislikes_worker(self, other: Worker) -> bool:
        """True if this worker dislikes sharing a shift with other."""
        return other.name in self.dislikes
