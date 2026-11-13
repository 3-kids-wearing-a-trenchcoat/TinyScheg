"""
The constants the penalty score is computed from, calculated once per run, before the search
(see docs/explanation/scoring.md). All durations are in hours.
"""
from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tinyscheg.model.schedule_input import ScoringParameters, Settings
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.model.worker import Worker
from tinyscheg.timing.datetime_range import DateTimeRange

_ONE_HOUR = dt.timedelta(hours=1)

# The like function l(x), with beta (a disliked partner) as the unit. Only the ratio alpha / beta matters, since the
# likes penalty is measured in units of beta; alpha is the neutral_partner parameter.
LIKED_PARTNER = 0.0
DISLIKED_PARTNER = 1.0


@dataclass(frozen=True, slots=True)
class WorkerConstants:
    """
    The constants of one worker's penalty.
    availability is av, the hours within the period the worker is available; worst_deficit is M_w, the largest
    total rest deficit they could have. likes and dislikes hold worker indexes.
    """
    availability: float
    worst_deficit: float
    likes: frozenset[int]
    dislikes: frozenset[int]


@dataclass(frozen=True, slots=True)
class ScoringConstants:
    """
    Everything the penalty of any (partial) assignment is computed from, besides the assignment itself.
    slot_hours[i] is the length of slot i in hours, and slot_load[i] its load for the workload penalty: a blend of its
    hours and of one average slot (ADR 0026); shared_slots is the number of slots in shifts of more than one slot
    (n_shared). The penalty's parts are flat (ADR 0032): workload_unit is what the workload penalty is measured in,
    mean slot load ** p / mean availability ** (p - 1), so that one shift of imbalance costs the same at any length;
    rest_unit is the mean M_w of the workers who could have a deficit, which keeps the average hour short costing the
    same at any length. pair_values[w][p] is what workers w and p add to the likes total as a pair, before dividing by
    the shift's other slots: both workers' like values of each other, computed once since the search asks for them at
    every step.
    """
    parameters: ScoringParameters
    min_rest: float
    slots: tuple[Slot, ...]
    shifts: tuple[Shift, ...]
    slot_hours: tuple[float, ...]
    slot_load: tuple[float, ...]
    workers: tuple[WorkerConstants, ...]
    shared_slots: int
    workload_unit: float
    rest_unit: float
    pair_values: tuple[tuple[float, ...], ...]


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
    mean_hours = math.fsum(slot_hours) / len(slot_hours) if slot_hours else 0.0

    def load(time: DateTimeRange) -> float:
        """A slot's load: its hours and one average slot, blended by the shift share (ADR 0026)."""
        return slot_load(hours(time.duration), mean_hours, parameters.shift_share)

    worker_constants = []
    for index, worker in enumerate(workers):
        ranges = sorted({slot.time for slot, domain in zip(slots, domains) if index in domain})
        worker_constants.append(WorkerConstants(
            availability=availability(worker, settings.period),
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
        workload_unit=workload_unit(worker_constants, [load(slot.time) for slot in slots], parameters.workload_power),
        rest_unit=rest_unit(worker_constants),
        pair_values=pair_values(worker_constants, parameters.neutral_partner))


def like_value(worker: WorkerConstants, partner: int, neutral_partner: float) -> float:
    """
    l(partner) for a worker: nothing for a liked partner, alpha for a neutral one, beta for a disliked one
    :param worker: WorkerConstants of the worker
    :param partner: int, the partner's index
    :param neutral_partner: float, alpha / beta
    :return: the like value, in units of beta
    """
    if partner in worker.likes:
        return LIKED_PARTNER
    if partner in worker.dislikes:
        return DISLIKED_PARTNER
    return neutral_partner * DISLIKED_PARTNER


def pair_values(workers: Sequence[WorkerConstants], neutral_partner: float) -> tuple[tuple[float, ...], ...]:
    """
    Every pair's value: what the two workers add to the likes total together, both their like values of each other
    :param workers: WorkerConstants of every worker, in input order
    :param neutral_partner: float, alpha / beta
    :return: values[w][p] for every pair of worker indexes (w == p included, as the likes bound may ask for it)
    """
    return tuple(tuple(like_value(workers[worker], partner, neutral_partner)
                       + like_value(workers[partner], worker, neutral_partner) for partner in range(len(workers)))
                 for worker in range(len(workers)))


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
    """
    The indexes of the ranges a worker could work next after ranges[first]: those starting after its end, by at least
    min_rest (never back to back)
    """
    return [later for later in range(first + 1, len(ranges))
            if (rest := hours(ranges[later].start - ranges[first].end)) > 0 and rest >= min_rest]


def workload_unit(workers: Sequence[WorkerConstants], loads: Sequence[float], power: int) -> float:
    """
    The unit the workload penalty is measured in (ADR 0032): the term av * (load / av) ** p of an average worker
    given one average slot, (mean load) ** p / (mean av) ** (p - 1). Measured in it, moving one average slot between
    two average workers with the same load costs about the same at any schedule length.
    :param workers: WorkerConstants of all workers
    :param loads: every slot's load
    :param power: p, the workload power
    :return: the unit; 0 if no worker has any availability or there are no slots
    """
    available = [worker.availability for worker in workers if worker.availability > 0]
    if not available or not loads:
        return 0.0
    return (math.fsum(loads) / len(loads)) ** power / (math.fsum(available) / len(available)) ** (power - 1)


def rest_unit(workers: Sequence[WorkerConstants]) -> float:
    """
    The scale of the rest penalty (ADR 0032): the mean M_w of the workers who could have a deficit. Each worker's
    hours short are divided by their own M_w, as before, then multiplied by this, so an hour short weighs more for a
    worker who could rarely be short, but the average hour costs the same at any schedule length.
    :param workers: WorkerConstants of all workers
    :return: the mean M_w; 0 if no worker can have a deficit
    """
    worst = [worker.worst_deficit for worker in workers if worker.worst_deficit > 0]
    return math.fsum(worst) / len(worst) if worst else 0.0
