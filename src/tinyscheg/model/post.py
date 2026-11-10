"""Posts: templates describing what needs to be manned, and when."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from tinyscheg.timing.daily_window import DailyWindow


@dataclass(frozen=True, slots=True)
class ShiftRules:
    """
    What each shift needs: its length, and how many workers of each role.
    roles keeps the input order of the roles, which is part of the stable slot order.
    """
    length: dt.timedelta
    roles: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        """Validate the rules."""
        object.__setattr__(self, "roles", tuple((role, count) for role, count in self.roles))
        if self.length <= dt.timedelta(0):
            raise ValueError(f"shift length must be positive, got {self.length}")
        role_names = [role for role, _ in self.roles]
        if len(set(role_names)) != len(role_names):
            raise ValueError(f"roles must not repeat, got {role_names}")
        for role, count in self.roles:
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"the count for role {role!r} must be a whole number of at least 0, got {count!r}")

    @property
    def workers_needed(self) -> int:
        """The total number of workers each shift needs."""
        return sum(count for _, count in self.roles)


@dataclass(frozen=True, slots=True)
class Variation:
    """A daily window during which a post's shifts follow different rules. Always fully specified."""
    window: DailyWindow
    rules: ShiftRules


@dataclass(frozen=True, slots=True)
class Post:
    """
    Something that needs to be manned, as a template for its shifts.
    rules is the general case; window is the daily window during which the post is active (None for always);
    variations override the rules during their own windows, and must not overlap one another.
    """
    name: str
    rules: ShiftRules
    window: DailyWindow | None = None
    variations: tuple[Variation, ...] = ()

    def __post_init__(self) -> None:
        """Store the variations as a tuple."""
        object.__setattr__(self, "variations", tuple(self.variations))
