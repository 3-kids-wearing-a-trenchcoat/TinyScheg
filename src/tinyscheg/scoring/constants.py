"""
The constants the penalty score is computed from, calculated once per run, before the search
(see docs/explanation/scoring.md). All durations are in hours.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tinyscheg.model.schedule_input import ScoringParameters, Settings
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.model.worker import Worker
from tinyscheg.timing.datetime_range import DateTimeRange

_ONE_HOUR = dt.timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class WorkerConstants:
    """
    The constants of one worker's penalty.
    availability is av, the hours within the period the worker is available; packable_load is H_max, the most load
    they could be given over any legal set of slots in their domain (ADR 0026); worst_deficit is M_w, the largest
    total rest deficit they could have. likes and dislikes hold worker indexes.
    """
    availability: float
    packable_load: float
    worst_deficit: float
    likes: frozenset[int]
    dislikes: frozenset[int]


@dataclass(frozen=True, slots=True)
class ScoringConstants:
    """
    Everything the penalty of any (partial) assignment is computed from, besides the assignment itself.
    slot_hours[i] is the length of slot i in hours, and slot_load[i] its load for the workload penalty: a blend of its
    hours and of one average slot (ADR 0026); shared_slots is the number of slots in shifts of more than one slot
    (n_shared); workload_scale is the workload penalty's largest possible value, sum(av * phi(H_max / av)).
    """
    parameters: ScoringParameters
    min_rest: float
    slots: tuple[Slot, ...]
    shifts: tuple[Shift, ...]
    slot_hours: tuple[float, ...]
    slot_load: tuple[float, ...]
    workers: tuple[WorkerConstants, ...]
    shared_slots: int
    workload_scale: float


def hours(length: dt.timedelta) -> float:
    """A duration in hours."""
    return length / _ONE_HOUR


def build_constants(settings: Settings, workers: Sequence[Worker], shifts: Sequence[Shift], slots: Sequence[Slot],
                    domains: Sequence[Sequence[int]]) -> ScoringConstants:
    """
    Calculate the scoring constants of a run
    :param settings: Settings, for the period, the minimum rest and the scoring parameters
    :param workers: all workers, in input order
    :param shifts: all shifts, in stable order
    :param slots: all slots, in stable order
    :param domains: for each slot, the indexes of the workers who can fill it (after the unary constraints)
    :return: ScoringConstants
    """
    parameters = settings.scoring
    min_rest = hours(settings.min_rest)
    index_of = {worker.name: index for index, worker in enumerate(workers)}
    slot_hours = tuple(hours(slot.time.duration) for slot in slots)
    mean_hours = sum(slot_hours) / len(slot_hours) if slot_hours else 0.0

    def load(time: DateTimeRange) -> float:
        """A slot's load: its hours and one average slot, blended by the shift share (ADR 0026)."""
        return slot_load(hours(time.duration), mean_hours, parameters.shift_share)

    worker_constants = []
    for index, worker in enumerate(workers):
        ranges = sorted({slot.time for slot, domain in zip(slots, domains) if index in domain})
        worker_constants.append(WorkerConstants(
            availability=availability(worker, settings.period),
            packable_load=packable_load(ranges, min_rest, load),
            worst_deficit=worst_deficit(ranges, min_rest, parameters.rest_factor),
            likes=frozenset(index_of[name] for name in worker.likes),
            dislikes=frozenset(index_of[name] for name in worker.dislikes)))
    return ScoringConstants(
        parameters=parameters,
        min_rest=min_rest,
        slots=tuple(slots),
        shifts=tuple(shifts),
        slot_hours=slot_hours,
        slot_load=tuple(load(slot.time) for slot in slots),
        workers=tuple(worker_constants),
        shared_slots=sum(len(shift.slots) for shift in shifts if len(shift.slots) > 1),
        workload_scale=workload_scale(worker_constants, parameters.workload_power))


def availability(worker: Worker, period: DateTimeRange) -> float:
    """
    The hours within a period during which a worker is available
    :param worker: Worker
    :param period: DateTimeRange, the schedule period
    :return: the period's length minus the worker's unavailability within it (overlapping ranges counted once)
    """
    unavailable = 0.0
    covered_until = period.start  # unavailability ranges are sorted by start; merge them as they come
    for away in worker.unavailable:
        clipped = away.intersection(period)
        if clipped is None or clipped.end <= covered_until:
            continue
        unavailable += hours(clipped.end - max(clipped.start, covered_until))
        covered_until = clipped.end
    return hours(period.duration) - unavailable


def slot_load(slot_hours: float, mean_hours: float, shift_share: float) -> float:
    """
    A slot's load for the workload penalty (ADR 0026): (1 - sigma) * its hours + sigma * the schedule's mean slot
    hours, so that with sigma = 0 only hours count, and with sigma = 1 every shift counts the same
    :param slot_hours: the slot's length in hours
    :param mean_hours: the mean length of all the schedule's slots, in hours
    :param shift_share: sigma
    :return: the load, in hours
    """
    return (1 - shift_share) * slot_hours + shift_share * mean_hours


def packable_load(ranges: Sequence[DateTimeRange], min_rest: float,
                  load: Callable[[DateTimeRange], float]) -> float:
    """
    The most load a worker could be given, over any legal sequence of the given time ranges
    :param ranges: the distinct time ranges of the slots in the worker's domain, sorted
    :param min_rest: the minimum rest between two shifts, in hours
    :param load: a time range's load (ADR 0026)
    :return: H_max: the heaviest path through the ranges, each weighted by its load (ADR 0015)
    """
    best = [0.0] * len(ranges)  # best[i]: the most load of a legal sequence starting with ranges[i]
    for first in reversed(range(len(ranges))):
        best[first] = load(ranges[first]) + max(
            (best[later] for later in _followers(ranges, first, min_rest)), default=0.0)
    return max(best, default=0.0)


def worst_deficit(ranges: Sequence[DateTimeRange], min_rest: float, rest_factor: float) -> float:
    """
    The largest total rest deficit a worker could have, over any legal sequence of the given time ranges
    :param ranges: the distinct time ranges of the slots in the worker's domain, sorted
    :param min_rest: the minimum rest between two shifts, in hours
    :param rest_factor: gamma; the rest target after a shift is gamma times its length
    :return: M_w: the heaviest path through the ranges, each step weighted by the deficit it causes (ADR 0014)
    """
    best = [0.0] * len(ranges)  # best[i]: the largest total deficit of a legal sequence starting with ranges[i]
    for first in reversed(range(len(ranges))):
        target = rest_factor * hours(ranges[first].duration)
        best[first] = max((max(0.0, target - hours(ranges[later].start - ranges[first].end)) + best[later]
                           for later in _followers(ranges, first, min_rest)), default=0.0)
    return max(best, default=0.0)


def _followers(ranges: Sequence[DateTimeRange], first: int, min_rest: float) -> list[int]:
    """The indexes of the ranges a worker could work next after ranges[first]: those starting min_rest after its end."""
    return [later for later in range(first + 1, len(ranges))
            if hours(ranges[later].start - ranges[first].end) >= min_rest]


def workload_scale(workers: Sequence[WorkerConstants], power: int) -> float:
    """
    The largest possible workload penalty, used to normalize it
    :param workers: WorkerConstants of all workers
    :param power: p, the workload power
    :return: the sum of av * (H_max / av) ** p over workers with some availability (ADR 0015)
    """
    return sum(worker.availability * (worker.packable_load / worker.availability) ** power
               for worker in workers if worker.availability > 0)
