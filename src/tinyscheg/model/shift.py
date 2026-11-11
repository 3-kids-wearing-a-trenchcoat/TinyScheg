"""Shifts and slots: the concrete times a post is manned, and the places in them that need a worker."""
from __future__ import annotations

from dataclasses import dataclass

from tinyscheg.model.post import Post
from tinyscheg.timing.datetime_range import DateTimeRange


@dataclass(frozen=True, slots=True)
class Slot:
    """
    A place for one worker of a given role in a shift: a variable of the CSP.
    index is the slot's position in the stable slot order, and shift_index the position of its shift. post and time
    repeat the shift's, so that constraint and scoring code doesn't need to look the shift up.
    """
    index: int
    shift_index: int
    post: Post
    time: DateTimeRange
    role: str


@dataclass(frozen=True, slots=True)
class Shift:
    """
    One post being manned for one continuous time range, by the workers filling its slots.
    index is the shift's position in the stable shift order; slots are in role order and are contiguous in the
    stable slot order.
    """
    index: int
    post: Post
    time: DateTimeRange
    slots: tuple[Slot, ...]

    def __post_init__(self) -> None:
        """Store the slots as a tuple."""
        object.__setattr__(self, "slots", tuple(self.slots))
