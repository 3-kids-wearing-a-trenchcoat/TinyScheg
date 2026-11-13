"""
The scheduling problem as a CSP: slots are the variables, workers the values.
Workers and slots are referred to by index: a worker's index is its position in the input, and a slot's index is its
position in the stable slot order.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from tinyscheg.model.schedule_input import PreviousSchedule, ScheduleInput, Settings
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.model.shift_generation import all_slots, generate_shifts
from tinyscheg.model.worker import Worker
from tinyscheg.timing.datetime_range import DateTimeRange


@dataclass(frozen=True, slots=True)
class Problem:
    """
    The fixed description of a scheduling CSP. It doesn't change during the search, which keeps its own state.
    domains[i] holds the indexes of the workers who can fill slot i, ascending (which is the order values are tried
    in); neighbours[i] holds the indexes of the slots that must get a different worker from slot i, ascending.
    interchangeable[i] holds the indexes of the other slots of slot i's shift that need the same role, ascending
    (empty for none, or if not given): swapping their workers changes nothing, so the search fills them in ascending
    worker order (ADR 0025).
    With a history (ADR 0031), the schedule is the history's shifts followed by the new period's, as one schedule
    already filled up to the new period: fixed[i] is the worker of history slot i, None for a new slot (empty if
    there's no history), and settings covers the whole schedule's period; it's None only for problems built by hand.
    """
    workers: tuple[Worker, ...]
    shifts: tuple[Shift, ...]
    slots: tuple[Slot, ...]
    domains: tuple[tuple[int, ...], ...]
    neighbours: tuple[tuple[int, ...], ...]
    min_rest: dt.timedelta
    interchangeable: tuple[tuple[int, ...], ...] = ()
    fixed: tuple[int | None, ...] = ()
    settings: Settings | None = None

    def is_fixed(self, slot_index: int) -> bool:
        """True if the slot is part of the history, with its worker fixed."""
        return bool(self.fixed) and self.fixed[slot_index] is not None

    @property
    def new_shifts(self) -> tuple[Shift, ...]:
        """The new period's shifts, the ones to fill: every shift if there's no history."""
        return tuple(shift for shift in self.shifts if not self.is_fixed(shift.slots[0].index))

    @property
    def new_slots(self) -> tuple[Slot, ...]:
        """The new period's slots."""
        return tuple(slot for slot in self.slots if not self.is_fixed(slot.index))


def build_problem(schedule_input: ScheduleInput) -> Problem:
    """
    Set up the CSP for a schedule: generate its shifts and slots, then their domains and difference constraints
    :param schedule_input: ScheduleInput, a validated input
    :return: the Problem
    """
    settings = schedule_input.settings
    if schedule_input.history:
        return _with_history(schedule_input)
    shifts = generate_shifts(schedule_input.posts, settings.period)
    slots = all_slots(shifts)
    return Problem(workers=schedule_input.workers,
                   shifts=shifts,
                   slots=slots,
                   domains=tuple(initial_domain(slot, schedule_input.workers) for slot in slots),
                   neighbours=difference_constraints(slots, settings.min_rest),
                   min_rest=settings.min_rest,
                   interchangeable=interchangeable_slots(slots),
                   settings=settings)


# --- a schedule with a history (ADR 0031) ---

def _with_history(schedule_input: ScheduleInput) -> Problem:
    """
    Set up the CSP for a schedule extending its history: one schedule from the history's start to the new period's
    end, whose history slots are already filled. They keep their workers, whatever the current rules, and aren't
    constrained with each other; the constraints between them and the new slots (overlap, minimum rest) are applied
    to the new slots' domains, as forward checking from the filled slots would.
    :param schedule_input: ScheduleInput, a validated input with a history
    :return: the Problem
    """
    settings = schedule_input.settings
    history = sorted(schedule_input.history, key=lambda previous: previous.schedule_input.settings.period.start)
    past: list[tuple[Shift, tuple[int, ...]]] = []
    for previous in history:
        past += _past_shifts(previous, schedule_input.workers)
    new = [(shift, ()) for shift in generate_shifts(schedule_input.posts, settings.period)]
    shifts = _renumbered([shift for shift, _ in past + new])
    slots = all_slots(shifts)
    fixed = tuple([worker for _, workers in past for worker in workers] + [None] * sum(len(s.slots) for s, _ in new))
    start = history[0].schedule_input.settings.period.start
    whole = Settings(DateTimeRange(start, settings.period.end), settings.min_rest, settings.scoring)
    workers = tuple(_whole_schedule_worker(worker, schedule_input, history) for worker in schedule_input.workers)
    neighbours = tuple(tuple(other for other in others if fixed[index] is None or fixed[other] is None)
                       for index, others in enumerate(difference_constraints(slots, settings.min_rest)))
    domains = []
    for slot in slots:
        if fixed[slot.index] is not None:
            domains.append((fixed[slot.index],))
        else:
            taken = {fixed[other] for other in neighbours[slot.index] if fixed[other] is not None}
            domains.append(tuple(worker for worker in initial_domain(slot, workers) if worker not in taken))
    return Problem(workers=workers, shifts=shifts, slots=slots, domains=tuple(domains), neighbours=neighbours,
                   min_rest=settings.min_rest, interchangeable=interchangeable_slots(slots), fixed=fixed,
                   settings=whole)


def _past_shifts(previous: PreviousSchedule, workers: Sequence[Worker]) -> list[tuple[Shift, tuple[int, ...]]]:
    """
    A previous schedule's shifts, generated from its own input, each with its workers as indexes into the current
    workers. Slots of workers who aren't in the current input (they've left) are dropped, and so are shifts left
    with no slots.
    """
    index_of = {worker.name: index for index, worker in enumerate(workers)}
    names = [worker.name for worker in previous.schedule_input.workers]
    shifts = generate_shifts(previous.schedule_input.posts, previous.schedule_input.settings.period)
    result = []
    for shift in shifts:
        kept = [(slot, index_of[names[previous.assignment[slot.index]]]) for slot in shift.slots
                if names[previous.assignment[slot.index]] in index_of]
        if kept:
            result.append((dataclasses.replace(shift, slots=tuple(slot for slot, _ in kept)),
                           tuple(worker for _, worker in kept)))
    return result


def _renumbered(shifts: Sequence[Shift]) -> tuple[Shift, ...]:
    """Shifts in stable order, with their indexes and their slots' indexes renumbered to their positions."""
    result = []
    slot_index = 0
    for shift_index, shift in enumerate(shifts):
        slots = []
        for slot in shift.slots:
            slots.append(dataclasses.replace(slot, index=slot_index, shift_index=shift_index))
            slot_index += 1
        result.append(dataclasses.replace(shift, index=shift_index, slots=tuple(slots)))
    return tuple(result)


def _whole_schedule_worker(worker: Worker, schedule_input: ScheduleInput,
                           history: Sequence[PreviousSchedule]) -> Worker:
    """
    A worker as they are over the whole schedule: unavailable when they were in a history input and unavailable
    there, when they weren't in it at all (they joined later), between periods, and when unavailable in the new
    period. So their availability is the time they were available in each period, and gaps count for no one.
    """
    periods = [previous.schedule_input.settings.period for previous in history] + [schedule_input.settings.period]
    away: list[DateTimeRange] = []
    for previous, period in zip(history, periods):
        then = next((other for other in previous.schedule_input.workers if other.name == worker.name), None)
        away += [period] if then is None else _within(then.unavailable, period)
    away += _within(worker.unavailable, schedule_input.settings.period)
    away += [DateTimeRange(earlier.end, later.start) for earlier, later in zip(periods, periods[1:])
             if earlier.end < later.start]
    return dataclasses.replace(worker, unavailable=tuple(away))


def _within(ranges: Sequence[DateTimeRange], period: DateTimeRange) -> list[DateTimeRange]:
    """The parts of the ranges inside a period."""
    return [part for part in (time.intersection(period) for time in ranges) if part is not None]


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
    """
    True if one worker can't fill both slots: they overlap, are back to back (one ends as the other starts), or are
    less than min_rest apart. Back to back is never allowed, even with a min_rest of 0.
    """
    rest = first.time.gap(second.time)  # zero if they overlap or touch
    return rest <= dt.timedelta(0) or rest < min_rest


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
            # Later slots start no earlier than this one, so once one starts after this slot's end, by at least the
            # rest period, every slot after it does too, and none of them can be constrained with this slot.
            if second.time.start >= rest_ends and second.time.start > first.time.end:
                break
            if must_differ(first, second, min_rest):
                neighbours[first_index].append(second_index)
                neighbours[second_index].append(first_index)
    return tuple(tuple(sorted(indexes)) for indexes in neighbours)


def interchangeable_slots(slots: Sequence[Slot]) -> tuple[tuple[int, ...], ...]:
    """
    Find the slots whose workers could be swapped without changing anything: those of the same shift needing the same
    role. They have the same time, length and role, so the same initial domain and constraints, and the scoring
    treats a shift's slots alike (ADR 0025).
    :param slots: all slots in stable order
    :return: for each slot, the indexes of the other slots of its shift with its role, ascending
    """
    groups: dict[tuple[int, str], list[int]] = {}
    for slot in slots:
        groups.setdefault((slot.shift_index, slot.role), []).append(slot.index)
    return tuple(tuple(other for other in groups[(slot.shift_index, slot.role)] if other != slot.index)
                 for slot in slots)


def unfillable_slots(problem: Problem) -> tuple[Slot, ...]:
    """
    Find the slots no worker can fill, which make the problem unsolvable before any search
    :param problem: Problem
    :return: the slots whose initial domain is empty, in stable order
    """
    return tuple(slot for slot, domain in zip(problem.slots, problem.domains) if not domain)
