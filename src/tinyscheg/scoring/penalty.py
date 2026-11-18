"""
The penalty score of a (partial) schedule (see docs/explanation/scoring.md): a weighted sum of the likes, workload
and rest penalties, each flat (ADR 0032): one disliked pairing, one shift of imbalance or one hour short costs the
same whatever the schedule's length. Lower is better, and filling another slot never lowers it.

An assignment holds a worker index per slot, in stable slot order, or None for a slot that isn't filled yet. Every
penalty is computed from scratch, with sums always taken in the same order (shifts, slots and workers in their stable
order), so the same assignment always gets exactly the same penalty, however it was reached (ADR 0012). Lists of
floats are added with math.fsum, which rounds only once, rather than sum(), whose rounding differs between Python
versions and interpreters (CPython 3.12+ compensates, 3.11 and PyPy don't): so the penalty, and which of equally
good schedules is kept, is the same on all of them.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from tinyscheg.model.shift import Shift
from tinyscheg.scoring.constants import (DISLIKED_PARTNER, MICROSECONDS_PER_HOUR, ScoringConstants, integer_power,
                                         like_value, rest_target)
from tinyscheg.scoring.whole_slots import own_whole_slot_bound, whole_slot_bound


# Each worker's rest shortfall goes through deficit ** REST_POWER (ADR 0036): squared, so that the same shortfall
# costs more on a worker who already has some
REST_POWER = 2


@dataclass(frozen=True, slots=True)
class Penalty:
    """A schedule's penalty: the weighted total, and each part before weighting, in its own units (ADR 0032)."""
    total: float
    likes: float
    workload: float
    rest: float


def score(constants: ScoringConstants, assignment: Sequence[int | None]) -> Penalty:
    """
    Score a (partial) schedule
    :param constants: ScoringConstants of the run
    :param assignment: a worker index per slot, or None for an unfilled slot
    :return: the Penalty; at least 0
    """
    parameters = constants.parameters
    likes = likes_penalty(constants, assignment)
    workload = workload_penalty(constants, assignment)
    rest = rest_penalty(constants, assignment)
    total = parameters.likes_weight * likes + parameters.workload_weight * workload + parameters.rest_weight * rest
    return Penalty(total, likes, workload, rest)


def likes_penalty(constants: ScoringConstants, assignment: Sequence[int | None]) -> float:
    """
    The likes penalty L**: for each filled slot in a shared shift, its worker's like value of the workers in the
    shift's other slots, averaged over those other slots (unfilled ones count 0)
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :return: L* / beta, in units of a disliked partner (ADR 0032); 0 if no shift has more than one slot
    """
    return normalized_likes(constants, likes_total(constants, assignment))


def likes_total(constants: ScoringConstants, assignment: Sequence[int | None]) -> float:
    """The likes penalty before normalizing: the sum of the like values over filled pairs, each over its shift's other
    slots."""
    total = 0.0
    for shift in constants.shifts:
        others = len(shift.slots) - 1
        if others == 0:
            continue
        workers = [assignment[slot.index] for slot in shift.slots]
        for position, worker in enumerate(workers):
            if worker is None:
                continue
            total += math.fsum(_like_value(constants, worker, partner)
                         for partner_position, partner in enumerate(workers)
                         if partner_position != position and partner is not None) / others
    return total


def _like_value(constants: ScoringConstants, worker: int, partner: int) -> float:
    """l(partner) for worker: nothing for a liked partner, alpha for a neutral one, beta for a disliked one."""
    return like_value(constants.workers[worker], partner, constants.parameters.neutral_partner)


def workload_penalty(constants: ScoringConstants, assignment: Sequence[int | None]) -> float:
    """
    The workload penalty W*: the sum of av * (assigned load / av) ** p, the load being a blend of hours and shifts
    (ADR 0026), in workload units (ADR 0032; workers with no availability are left out)
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :return: W / workload_unit; 0 if no worker can be assigned anything
    """
    if constants.workload_unit == 0:
        return 0.0
    return workload_total(constants, assignment) / constants.workload_unit


def workload_total(constants: ScoringConstants, assignment: Sequence[int | None]) -> float:
    """The workload penalty before normalizing: the sum of av * (assigned load / av) ** p."""
    power = constants.parameters.workload_power
    assigned_load = _assigned_load(constants, assignment)
    return math.fsum(worker.availability * integer_power(assigned_load[index] / worker.availability, power)
               for index, worker in enumerate(constants.workers) if worker.availability > 0)


def lower_bound(constants: ScoringConstants, assignment: Sequence[int | None],
                domains: Sequence[Sequence[int]]) -> float:
    """
    A lower bound on the total penalty of every complete schedule that extends a partial one (ADR 0024): the lowest
    likes penalty the shifts' pairings could still give (likes_lower_bound), the lowest workload penalty the remaining
    slots could give (workload_lower_bound), and the rest penalty so far, which filling slots never lowers. Neither
    look-ahead assumes anything about shift lengths, so the bound holds for asymmetric schedules too.
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None for an unfilled slot
    :param domains: for each slot, the workers who can still fill it (only the unfilled slots' are used)
    :return: a number at most the total penalty of every completion, and at least the partial schedule's own
    """
    parameters = constants.parameters
    return (parameters.likes_weight * likes_lower_bound(constants, assignment, domains)
            + parameters.workload_weight * workload_lower_bound(constants, assignment, domains)
            + parameters.rest_weight * rest_penalty(constants, assignment))


def likes_lower_bound(constants: ScoringConstants, assignment: Sequence[int | None],
                      domains: Sequence[Sequence[int]]) -> float:
    """
    The lowest likes penalty any completion of a partial schedule could have. In a complete schedule, each
    pair of slots in a shared shift adds both workers' like values of each other, over the shift's other slots; a
    pair with an unfilled slot adds at least the lowest value any workers still in their domains could give
    (choosing each pair's best independently, and even the same worker twice, only lowers the bound)
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :param domains: for each slot, the workers who can still fill it
    :return: at least likes_penalty(assignment); 0 if no shift has more than one slot
    """
    total = math.fsum(shift_likes_lower_bound(constants, shift, assignment, domains) for shift in constants.shifts)
    return normalized_likes(constants, total)


def shift_likes_lower_bound(constants: ScoringConstants, shift: Shift, assignment: Sequence[int | None],
                            domains: Sequence[Sequence[int]]) -> float:
    """
    One shift's share of likes_lower_bound, before normalizing: for each pair of its slots, the lowest pair_like_value
    the slots' workers (or, for an unfilled slot, any worker still in its domain) could give, over the shift's other
    slots
    :param constants: ScoringConstants
    :param shift: Shift
    :param assignment: a worker index per slot, or None
    :param domains: for each slot, the workers who can still fill it
    :return: the shift's share; 0 for a shift of one slot
    """
    others = len(shift.slots) - 1
    if others == 0:
        return 0.0
    candidates = [(assignment[slot.index],) if assignment[slot.index] is not None else domains[slot.index]
                  for slot in shift.slots]
    values = constants.pair_values
    total = 0.0
    for first in range(len(candidates)):
        for second in range(first + 1, len(candidates)):
            if not candidates[first] or not candidates[second]:
                continue  # an empty domain: there's no completion at all, so any value bounds it; 0 is the lowest
            total += min(values[worker][partner]
                         for worker in candidates[first] for partner in candidates[second]) / others
    return total


def pair_like_value(constants: ScoringConstants, worker: int, partner: int) -> float:
    """What a pair adds to the likes penalty, before dividing by the other slots: both workers' like values of each
    other."""
    return constants.pair_values[worker][partner]


def normalized_likes(constants: ScoringConstants, total: float) -> float:
    """A likes total (the sum of like values, each over its shift's other slots) in units of a disliked partner."""
    return total / DISLIKED_PARTNER


def workload_lower_bound(constants: ScoringConstants, assignment: Sequence[int | None],
                         domains: Sequence[Sequence[int]]) -> float:
    """
    The lowest workload penalty any completion of a partial schedule could have: the higher of two bounds
    (workload_bound_total) on how the load of the unfilled slots could go to workers in their domains, each worker
    gaining at most the load of the unfilled slots they're in the domain of. Which slots overlap is ignored, so the
    bound may be lower than reachable.
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :param domains: for each slot, the workers who can still fill it
    :return: at least workload_penalty(assignment)
    """
    if constants.workload_unit == 0:
        return 0.0
    assigned_load = _assigned_load(constants, assignment)
    caps = [0.0] * len(constants.workers)
    own = constants.own_whole_slot_sets
    counts: list[Any] = ([[0] * len(constants.load_classes) for _ in constants.workers] if own
                         else [0] * len(constants.load_classes))
    remaining = 0.0
    for slot, worker in enumerate(assignment):
        if worker is None:
            remaining += constants.slot_load[slot]
            load_class = constants.slot_load_class[slot]
            if not own:
                counts[load_class] += 1
            for candidate in domains[slot]:
                caps[candidate] += constants.slot_load[slot]
                if own:
                    counts[candidate][load_class] += 1
    return workload_bound_total(constants, assigned_load, caps, remaining, counts) / constants.workload_unit


def workload_bound_total(constants: ScoringConstants, assigned_load: Sequence[float], caps: Sequence[float],
                         remaining: float, counts: Sequence[Any]) -> float:
    """
    workload_lower_bound before normalizing, from the loads so far and what's left to hand out; the higher of:
    * water-filling (ADR 0024): each worker's term av * (load / av) ** p is convex, so the total is lowest when the
      load tops up the least-loaded workers to a common level of load / av, each only up to their cap, as water
      fills vessels of different heights (Jensen's inequality);
    * whole slots (ADR 0040, tinyscheg.scoring.whole_slots): each unfilled slot's load goes whole to one worker; with
      each worker's own sets (ADR 0046, chosen per run by ADR 0047), they take only slots in their own domain.
    :param constants: ScoringConstants
    :param assigned_load: each worker's load so far
    :param caps: each worker's cap, the load of the unfilled slots in their domains
    :param remaining: the load of the unfilled slots
    :param counts: for each of constants.load_classes, how many unfilled slots have that load; with each worker's own
    sets (constants.own_whole_slot_sets), that per worker, counting the slots in their domain
    :return: at least workload_total(assignment)
    """
    filled, level = water_filling(constants, assigned_load, caps, remaining)
    whole = whole_slots(constants, assigned_load, caps, remaining, counts, level)
    return filled if whole is None else max(filled, whole)


def water_filling(constants: ScoringConstants, assigned_load: Sequence[float], caps: Sequence[float],
                  remaining: float) -> tuple[float, float]:
    """
    The water-filling part of workload_bound_total, before normalizing
    :param constants: ScoringConstants
    :param assigned_load: each worker's load so far
    :param caps: each worker's cap
    :param remaining: the load of the unfilled slots
    :return: (the bound, the water level the remaining load raises the workers to)
    """
    power = constants.parameters.workload_power
    pool: list[tuple[float, float, float]] = []  # (load / av, av, highest load / av) per worker
    for index, worker in enumerate(constants.workers):
        if worker.availability > 0:
            pool.append((assigned_load[index] / worker.availability, worker.availability,
                         (assigned_load[index] + caps[index]) / worker.availability))
    level = _water_level(pool, remaining)
    filled = math.fsum(availability * integer_power(min(max(ratio, level), highest), power)
                       for ratio, availability, highest in pool)
    return filled, level


def whole_slots(constants: ScoringConstants, assigned_load: Sequence[float], caps: Sequence[float], remaining: float,
                counts: Sequence[Any], level: float) -> float | None:
    """
    The whole-slot part of workload_bound_total, before normalizing (tinyscheg.scoring.whole_slots)
    :param constants: ScoringConstants
    :param assigned_load: each worker's load so far
    :param caps: each worker's cap
    :param remaining: the load of the unfilled slots
    :param counts: as workload_bound_total takes them: per load class, or with each worker's own sets, per worker and
    load class
    :param level: the water level, from water_filling
    :return: the bound, or None where it doesn't apply
    """
    power = constants.parameters.workload_power
    availabilities = [worker.availability for worker in constants.workers]
    if constants.own_whole_slot_sets:
        return own_whole_slot_bound(power, availabilities, assigned_load, caps, remaining, counts,
                                    constants.load_classes, level)
    classes = [(load, count) for load, count in zip(constants.load_classes, counts) if count > 0]
    return whole_slot_bound(power, availabilities, assigned_load, caps, remaining, classes, level)


def _water_level(pool: list[tuple[float, float, float]], remaining: float) -> float:
    """
    The common level of load / av that the remaining load raises the workers of the pool to, each worker only up to
    their highest; workers already above it keep their own
    :param pool: (load / av, av, highest load / av) per worker
    :param remaining: the load to spread
    :return: the level; 0 if there's nothing to spread
    """
    if remaining <= 0 or not pool:
        return 0.0
    # Raising the level from L takes load at a rate (slope) equal to the availability of the workers rising at L:
    # each starts rising at their own load / av and stops at their highest. Sweep the points where the slope
    # changes, in order, until the remaining load is spread.
    changes = sorted([(ratio, availability) for ratio, availability, highest in pool if highest > ratio]
                     + [(highest, -availability) for ratio, availability, highest in pool if highest > ratio])
    if not changes:
        return 0.0  # nobody can take any load
    level, spread, slope = changes[0][0], 0.0, 0.0
    for point, change in changes:
        if slope > 0 and spread + slope * (point - level) >= remaining:
            return level + (remaining - spread) / slope
        spread += slope * (point - level)
        level, slope = point, slope + change
    return level  # every worker is at their highest: the caps can't take all the load


def _assigned_load(constants: ScoringConstants, assignment: Sequence[int | None]) -> list[float]:
    """Each worker's total assigned load (ADR 0026): their hours and shifts, blended by the shift share."""
    totals = [0.0] * len(constants.workers)
    for slot_index, worker in enumerate(assignment):
        if worker is not None:
            totals[worker] += constants.slot_load[slot_index]
    return totals


def rest_penalty(constants: ScoringConstants, assignment: Sequence[int | None]) -> float:
    """
    The rest penalty R** (ADR 0036): for each worker, the hours D by which their rests fall short of their targets
    in all, and their term rest_unit / M_w * D ** REST_POWER / rest_scale. Squared (REST_POWER = 2), the same
    shortfall costs more on a worker who already has some, so it's spread rather than concentrated; measured in
    typical targets (rest_scale), the square doesn't depend on the unit of time. Divided by the worker's worst
    possible deficit M_w and multiplied by the mean M_w (rest_unit, ADR 0032): an hour short weighs more for a worker
    who could rarely be short.
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :return: the sum over workers; workers with M_w = 0 can never have a deficit and count 0
    """
    total = 0.0
    for worker, deficit in enumerate(worker_deficits(constants, assignment)):
        total += rest_term(constants, worker, deficit)
    return total


def worker_deficits(constants: ScoringConstants, assignment: Sequence[int | None]) -> list[float]:
    """
    Each worker's rest deficit: the hours by which their rests fall short of their targets, in all
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :return: a deficit in hours per worker, in worker order
    """
    deficits = []
    for worker, slot_indexes in enumerate(_slots_by_worker(constants, assignment)):
        # Slots in stable order are sorted by start time, and a worker's slots never overlap, so consecutive slots
        # are consecutive shifts; the rests before the first and after the last aren't judged.
        deficit = 0.0
        for earlier, later in zip(slot_indexes, slot_indexes[1:]):
            deficit += rest_deficit(constants, worker, earlier, later)
        deficits.append(deficit)
    return deficits


def rest_term(constants: ScoringConstants, worker: int, deficit: float) -> float:
    """
    A worker's term of the rest penalty, convex in their deficit (ADR 0036). The power is multiplied out one factor
    at a time, which rounds the same on every interpreter: float ** int doesn't (CPython's pow can differ from
    repeated multiplication in the last digit).
    :param constants: ScoringConstants
    :param worker: int, the worker's index
    :param deficit: float, their deficit in hours
    :return: rest_unit / M_w * deficit ** REST_POWER / rest_scale; 0 if they can never have a deficit
    """
    worst = constants.workers[worker].worst_deficit
    if worst == 0 or constants.rest_scale <= 0:
        return 0.0
    term = constants.rest_unit / worst
    for _ in range(REST_POWER):
        term *= deficit
    return term / constants.rest_scale


def rest_deficit(constants: ScoringConstants, worker: int, earlier: int, later: int) -> float:
    """
    The hours by which the rest between two consecutive slots of a worker falls short of its target: gamma times the
    mean of the two slots' lengths (ADR 0036). The rest counts only the time the worker was available: unavailable
    time is neither work nor rest (ADR 0038).
    :param constants: ScoringConstants
    :param worker: int, the worker's index
    :param earlier: int, the earlier slot's index
    :param later: int, the later slot's index
    :return: the deficit, in hours
    """
    away = constants.unavailable_at_start[worker][later] - constants.unavailable_at_end[worker][earlier]
    # in whole microseconds worked out once, which gives exactly the hours datetime arithmetic would
    gap = constants.slot_start_microseconds[later] - constants.slot_end_microseconds[earlier]
    rest = gap / MICROSECONDS_PER_HOUR - away
    target = rest_target(constants.rest_factor, constants.slot_hours[earlier], constants.slot_hours[later])
    return max(0.0, target - rest)


def _slots_by_worker(constants: ScoringConstants, assignment: Sequence[int | None]) -> list[list[int]]:
    """For each worker, the indexes of the slots assigned to them, in stable order."""
    slots: list[list[int]] = [[] for _ in constants.workers]
    for slot_index, worker in enumerate(assignment):
        if worker is not None:
            slots[worker].append(slot_index)
    return slots

