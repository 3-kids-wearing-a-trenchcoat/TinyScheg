"""
The constants the penalty score is computed from, calculated once per run, before the search
(see docs/explanation/scoring.md). All durations are in hours.
"""
from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tinyscheg.model.schedule_input import ROLE_AWARE_BOUND_OFF, ROLE_AWARE_BOUND_ON, ScoringParameters, Settings
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.model.worker import Worker
from tinyscheg.timing.datetime_range import DateTimeRange

_ONE_HOUR = dt.timedelta(hours=1)
_ONE_MICROSECOND = dt.timedelta(microseconds=1)
# An hour in whole microseconds, the unit timedelta keeps its durations in: a rest's hours are its microseconds divided
# by this, which rounds exactly as dividing the timedelta by an hour does (both divide the same two integers)
MICROSECONDS_PER_HOUR = _ONE_HOUR // _ONE_MICROSECOND

# The like function l(x), with beta (a disliked partner) as the unit. Only the ratio alpha / beta matters, since the
# likes penalty is measured in units of beta; alpha is the neutral_partner parameter.
LIKED_PARTNER = 0.0
DISLIKED_PARTNER = 1.0


# The automatic choice of the role-aware bound (ADR 0047): each worker's own whole-slot sets where the slots' domains
# are of at least this many kinds and at least this share of the load lies outside them. Fitted on the benchmark
# inputs, alone and as day 2 (2026-11-17)
AUTO_MIN_DISTINCT_DOMAINS = 3
AUTO_MIN_LOAD_OUTSIDE = 0.2

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
    same at any length. rest_factor is gamma, derived from the input (ADR 0036): the schedule's free hours per hour
    of work; rest_scale is one typical rest target, gamma times the mean slot length, the unit each worker's squared
    hours short are measured in. unavailable_at_start[w][i] and unavailable_at_end[w][i] are worker w's unavailable
    hours before slot i starts and ends, so that a rest counts only the time they were available (ADR 0038).
    slot_start_microseconds[i] and slot_end_microseconds[i] are when slot i starts and ends, in whole microseconds from
    the first slot's start: worked out once, so that the search's rests need no datetime arithmetic (2026-11-18:
    PyPy runs datetime as Python code). pair_values[w][p] is what workers w and p add to the likes total as a pair, before
    dividing by the shift's other slots: both workers' like values of each other, computed once since the search asks
    for them at every step. load_classes holds the schedule's distinct slot loads, ascending, and slot_load_class[i]
    the index of slot i's load among them, for the workload bound in whole slots (ADR 0040). own_whole_slot_sets says
    whether that bound takes each worker's sets from their own domain (ADR 0046), as the role_aware_bound setting
    resolves for the run (ADR 0047).
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
    rest_factor: float
    rest_scale: float
    unavailable_at_start: tuple[tuple[float, ...], ...]
    unavailable_at_end: tuple[tuple[float, ...], ...]
    slot_start_microseconds: tuple[int, ...]
    slot_end_microseconds: tuple[int, ...]
    pair_values: tuple[tuple[float, ...], ...]
    load_classes: tuple[float, ...]
    slot_load_class: tuple[int, ...]
    own_whole_slot_sets: bool


def hours(length: dt.timedelta) -> float:
    """A duration in hours."""
    return length / _ONE_HOUR


def whole_microseconds(length: dt.timedelta) -> int:
    """A duration in whole microseconds, exactly (timedelta keeps its durations as whole microseconds)."""
    return length // _ONE_MICROSECOND


def build_constants(settings: Settings, workers: Sequence[Worker], shifts: Sequence[Shift], slots: Sequence[Slot],
                    domains: Sequence[Sequence[int]]) -> ScoringConstants:
    """
    Calculate the scoring constants of a run
    :param settings: Settings, for the period, the minimum rest, the scoring parameters and the role-aware bound
    :param workers: all workers, in input order
    :param shifts: all shifts, in stable order
    :param slots: all slots, in stable order
    :param domains: for each slot, the indexes of the workers who could fill it from scratch, as
    Problem.scoring_domains gives them: with a history, every worker who could have filled a history slot, not only
    the one who did (ADR 0037)
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

    available = [availability(worker, settings.period) for worker in workers]
    factor = rest_factor(available, slot_hours)
    loads = tuple(load(slot.time) for slot in slots)
    classes, slot_classes = load_classes(loads)
    worker_constants = []
    for index, worker in enumerate(workers):
        ranges = sorted({slot.time for slot, domain in zip(slots, domains) if index in domain})
        worker_constants.append(WorkerConstants(
            availability=available[index],
            worst_deficit=worst_deficit(ranges, min_rest, factor, worker.unavailable),
            likes=frozenset(index_of[name] for name in worker.likes),
            dislikes=frozenset(index_of[name] for name in worker.dislikes)))
    origin = slots[0].time.start if slots else None
    return ScoringConstants(
        parameters=parameters,
        min_rest=min_rest,
        slots=tuple(slots),
        shifts=tuple(shifts),
        slot_hours=slot_hours,
        slot_load=loads,
        workers=tuple(worker_constants),
        shared_slots=sum(len(shift.slots) for shift in shifts if len(shift.slots) > 1),
        workload_unit=workload_unit(worker_constants, list(loads), parameters.workload_power),
        rest_unit=rest_unit(worker_constants),
        rest_factor=factor,
        rest_scale=factor * mean_hours,
        unavailable_at_start=tuple(tuple(unavailable_before(worker.unavailable, slot.time.start) for slot in slots)
                                   for worker in workers),
        unavailable_at_end=tuple(tuple(unavailable_before(worker.unavailable, slot.time.end) for slot in slots)
                                 for worker in workers),
        slot_start_microseconds=tuple(whole_microseconds(slot.time.start - origin) for slot in slots),
        slot_end_microseconds=tuple(whole_microseconds(slot.time.end - origin) for slot in slots),
        pair_values=pair_values(worker_constants, parameters.neutral_partner),
        load_classes=classes,
        slot_load_class=slot_classes,
        own_whole_slot_sets=uses_own_whole_slot_sets(settings.role_aware_bound, len(workers), domains, loads))


def uses_own_whole_slot_sets(setting: str, workers: int, domains: Sequence[Sequence[int]],
                             loads: Sequence[float]) -> bool:
    """
    Whether the whole-slot bound takes each worker's sets from their own domain (ADR 0046), from the role_aware_bound
    setting: on, off, or auto (ADR 0047). Each worker's own sets prune more only where roles and unavailability narrow
    the domains in more than one way, and their bookkeeping costs about a fifth more per node, so auto chooses them
    where the domains are of at least AUTO_MIN_DISTINCT_DOMAINS kinds and at least AUTO_MIN_LOAD_OUTSIDE of the load
    lies outside them (each slot's load, times the share of workers who can't take it)
    :param setting: one of ROLE_AWARE_BOUND_CHOICES
    :param workers: the number of workers
    :param domains: each slot's domain, as build_constants takes them
    :param loads: each slot's load
    :return: True for each worker's own sets, False for the global ones
    """
    if setting == ROLE_AWARE_BOUND_ON:
        return True
    if setting == ROLE_AWARE_BOUND_OFF:
        return False
    total, outside = 0.0, 0.0
    for domain, load in zip(domains, loads):  # plain loops round the same on every interpreter, like fsum
        total += load
        outside += load * (workers - len(domain))
    distinct = len({tuple(domain) for domain in domains})
    return (distinct >= AUTO_MIN_DISTINCT_DOMAINS and workers > 0 and total > 0
            and outside / (workers * total) >= AUTO_MIN_LOAD_OUTSIDE)


def load_classes(loads: Sequence[float]) -> tuple[tuple[float, ...], tuple[int, ...]]:
    """
    Group the slots by their load, for the workload bound in whole slots (ADR 0040). Loads are grouped only when
    exactly equal, as slots of the same length are: a load a rounding apart gets a class of its own, which only
    makes the bound a little looser
    :param loads: each slot's load, in stable slot order
    :return: (the distinct loads, ascending; for each slot, the index of its load among them)
    """
    classes = tuple(sorted(set(loads)))
    index_of = {load: index for index, load in enumerate(classes)}
    return classes, tuple(index_of[load] for load in loads)


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


def unavailable_before(unavailable: Sequence[DateTimeRange], moment: dt.datetime) -> float:
    """
    How many hours of a worker's unavailability fall before a moment (ADR 0038): what a rest ending then and starting
    at an earlier moment leaves out, as the difference of two of these
    :param unavailable: the worker's unavailability, sorted by start (as Worker keeps it); overlaps count once
    :param moment: datetime.datetime
    :return: the hours, 0.0 exactly for a worker with no unavailability before the moment
    """
    total = 0.0
    covered_until: dt.datetime | None = None  # the end of the unavailability counted so far
    for away in unavailable:
        if away.start >= moment:
            break
        start = away.start if covered_until is None else max(away.start, covered_until)
        end = min(away.end, moment)
        if end > start:
            total += hours(end - start)
        covered_until = away.end if covered_until is None else max(covered_until, away.end)
    return total


def rest_factor(available: Sequence[float], slot_hours: Sequence[float]) -> float:
    """
    The rest factor gamma, derived from the input (ADR 0036): the schedule's free hours per hour of work. Fair shares
    of work being proportional to availability, it's every worker's free time divided by their fair share of hours,
    so a worker who works their share, spread evenly, gets this many hours of rest per hour of work.
    :param available: each worker's available hours (over the whole schedule, history included)
    :param slot_hours: each slot's length in hours
    :return: (total available hours - total slot hours) / total slot hours; 0 if there are no slots
    """
    work = math.fsum(slot_hours)
    return (math.fsum(available) - work) / work if work > 0 else 0.0


def rest_target(rest_factor: float, earlier_hours: float, later_hours: float) -> float:
    """
    The rest target between two consecutive shifts of a worker (ADR 0036): gamma times the mean of their lengths, so
    that each shift sits in the middle of its share of free time, and the same two shifts cost the same in either
    order
    :param rest_factor: gamma
    :param earlier_hours: the earlier shift's length in hours
    :param later_hours: the later shift's length in hours
    :return: the target, in hours
    """
    return rest_factor * (earlier_hours + later_hours) / 2


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


def worst_deficit(ranges: Sequence[DateTimeRange], min_rest: float, rest_factor: float,
                  unavailable: Sequence[DateTimeRange] = ()) -> float:
    """
    The largest total rest deficit a worker could have, over any legal sequence of the given time ranges
    :param ranges: the distinct time ranges of the slots in the worker's domain, sorted
    :param min_rest: the minimum rest between two shifts, in hours (on the clock: which sequences are legal)
    :param rest_factor: gamma; the target for the rest between two shifts is gamma times their mean length
    :param unavailable: the worker's unavailability, sorted; a rest counts only the time they're available (ADR 0038)
    :return: M_w: the heaviest path through the ranges, each step weighted by the deficit it causes (ADR 0014)
    """
    away_at_start = [unavailable_before(unavailable, time.start) for time in ranges]
    away_at_end = [unavailable_before(unavailable, time.end) for time in ranges]
    best = [0.0] * len(ranges)  # best[i]: the largest total deficit of a legal sequence starting with ranges[i]
    for first in reversed(range(len(ranges))):
        length = hours(ranges[first].duration)
        best[first] = max((max(0.0, rest_target(rest_factor, length, hours(ranges[later].duration))
                                - (hours(ranges[later].start - ranges[first].end)
                                   - (away_at_start[later] - away_at_end[first]))) + best[later]
                           for later in _followers(ranges, first, min_rest)), default=0.0)
    return max(best, default=0.0)


def _followers(ranges: Sequence[DateTimeRange], first: int, min_rest: float) -> list[int]:
    """
    The indexes of the ranges a worker could work next after ranges[first]: those starting after its end, by at least
    min_rest (never back to back)
    """
    return [later for later in range(first + 1, len(ranges))
            if (rest := hours(ranges[later].start - ranges[first].end)) > 0 and rest >= min_rest]


def integer_power(base: float, exponent: int) -> float:
    """
    base ** exponent for a whole exponent, multiplied out one factor at a time. float ** int rounds differently in the
    last digit from one interpreter to another (CPython's pow differs from repeated multiplication for about one value
    in a thousand), which could make CPython and PyPy break a tie differently; multiplication rounds the same on both.
    :param base: float
    :param exponent: int, at least 0
    :return: base multiplied by itself exponent times (1.0 for 0)
    """
    result = 1.0
    for _ in range(exponent):
        result *= base
    return result


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
    return (integer_power(math.fsum(loads) / len(loads), power)
            / integer_power(math.fsum(available) / len(available), power - 1))


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
