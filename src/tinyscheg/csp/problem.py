"""
The scheduling problem as a CSP: slots are the variables, workers the values.
Workers and slots are referred to by index: a worker's index is its position in the input, and a slot's index is its
position in the stable slot order.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.model.shift_generation import all_slots, generate_shifts
from tinyscheg.model.worker import Worker


@dataclass(frozen=True, slots=True)
class Problem:
    """
    The fixed description of a scheduling CSP. It doesn't change during the search, which keeps its own state.
    domains[i] holds the indexes of the workers who can fill slot i, ascending (which is the order values are tried
    in); neighbours[i] holds the indexes of the slots that must get a different worker from slot i, ascending.
    """
    workers: tuple[Worker, ...]
    shifts: tuple[Shift, ...]
    slots: tuple[Slot, ...]
    domains: tuple[tuple[int, ...], ...]
    neighbours: tuple[tuple[int, ...], ...]
    min_rest: dt.timedelta


def build_problem(schedule_input: ScheduleInput) -> Problem:
    """
    Set up the CSP for a schedule: generate its shifts and slots, then their domains and difference constraints
    :param schedule_input: ScheduleInput, a validated input
    :return: the Problem
    """
    settings = schedule_input.settings
    shifts = generate_shifts(schedule_input.posts, settings.period)
    slots = all_slots(shifts)
    return Problem(workers=schedule_input.workers,
                   shifts=shifts,
                   slots=slots,
                   domains=tuple(initial_domain(slot, schedule_input.workers) for slot in slots),
                   neighbours=difference_constraints(slots, settings.min_rest),
                   min_rest=settings.min_rest)


def initial_domain(slot: Slot, workers: Sequence[Worker]) -> tuple[int, ...]:
    """
    Apply the unary constraints to a slot
    :param slot: Slot
    :param workers: all workers, in input order
    :return: the indexes of the workers who have the slot's role and are available for its whole time, ascending
    """
    return tuple(index for index, worker in enumerate(workers)
                 if worker.has_role(slot.role) and worker.is_available(slot.time))


def must_differ(first: Slot, second: Slot, min_rest: dt.timedelta) -> bool:
    """True if the two slots overlap or are less than min_rest apart, so one worker can't fill both."""
    return first.time.overlaps(second.time) or first.time.gap(second.time) < min_rest


def difference_constraints(slots: Sequence[Slot], min_rest: dt.timedelta) -> tuple[tuple[int, ...], ...]:
    """
    Find every pair of slots that must be filled by different workers
    :param slots: all slots in stable order, which is sorted by start time
    :param min_rest: datetime.timedelta, the minimum rest between two of a worker's shifts
    :return: for each slot, the indexes of the slots it's constrained with, ascending; constraints are symmetric
    """
    neighbours: list[list[int]] = [[] for _ in slots]
    for first_index, first in enumerate(slots):
        rest_ends = first.time.end + min_rest
        for second_index in range(first_index + 1, len(slots)):
            second = slots[second_index]
            # Later slots start no earlier than this one, so once one starts after this slot's end plus the rest
            # period, every slot after it does too, and none of them can be constrained with this slot.
            if second.time.start >= rest_ends:
                break
            if must_differ(first, second, min_rest):
                neighbours[first_index].append(second_index)
                neighbours[second_index].append(first_index)
    return tuple(tuple(sorted(indexes)) for indexes in neighbours)


def unfillable_slots(problem: Problem) -> tuple[Slot, ...]:
    """
    Find the slots no worker can fill, which make the problem unsolvable before any search
    :param problem: Problem
    :return: the slots whose initial domain is empty, in stable order
    """
    return tuple(slot for slot, domain in zip(problem.slots, problem.domains) if not domain)
