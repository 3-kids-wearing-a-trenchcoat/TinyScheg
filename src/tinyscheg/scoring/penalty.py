"""
The penalty score of a (partial) schedule (see docs/explanation/scoring.md): a weighted sum of the likes, workload
and rest penalties, each normalized to [0, k] for k workers. Lower is better, and filling another slot never lowers
it.

An assignment holds a worker index per slot, in stable slot order, or None for a slot that isn't filled yet. Every
penalty is computed from scratch, with sums always taken in the same order (shifts, slots and workers in their stable
order), so the same assignment always gets exactly the same penalty, however it was reached (ADR 0012).
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from tinyscheg.scoring.constants import ScoringConstants, hours

# The like function l(x), with beta (a disliked partner) as the unit. Only the ratio alpha / beta matters, since the
# likes penalty is divided by beta to normalize it; alpha is the neutral_partner parameter.
LIKED_PARTNER = 0.0
DISLIKED_PARTNER = 1.0


@dataclass(frozen=True, slots=True)
class Penalty:
    """A schedule's penalty: the weighted total, and each normalized part before weighting."""
    total: float
    likes: float
    workload: float
    rest: float


def score(constants: ScoringConstants, assignment: Sequence[int | None]) -> Penalty:
    """
    Score a (partial) schedule
    :param constants: ScoringConstants of the run
    :param assignment: a worker index per slot, or None for an unfilled slot
    :return: the Penalty; its total lies in [0, k]
    """
    parameters = constants.parameters
    likes = likes_penalty(constants, assignment)
    workload = workload_penalty(constants, assignment)
    rest = rest_penalty(constants, assignment)
    total = parameters.likes_weight * likes + parameters.workload_weight * workload + parameters.rest_weight * rest
    return Penalty(total, likes, workload, rest)


def likes_penalty(constants: ScoringConstants, assignment: Sequence[int | None]) -> float:
    """
    The normalized likes penalty L**: for each filled slot in a shared shift, its worker's like value of the workers
    in the shift's other slots, averaged over those other slots (unfilled ones count 0)
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :return: k * L* / (beta * n_shared), in [0, k]; 0 if no shift has more than one slot
    """
    if constants.shared_slots == 0:
        return 0.0
    total = 0.0
    for shift in constants.shifts:
        others = len(shift.slots) - 1
        if others == 0:
            continue
        workers = [assignment[slot.index] for slot in shift.slots]
        for position, worker in enumerate(workers):
            if worker is None:
                continue
            total += sum(_like_value(constants, worker, partner)
                         for partner_position, partner in enumerate(workers)
                         if partner_position != position and partner is not None) / others
    return len(constants.workers) * total / (DISLIKED_PARTNER * constants.shared_slots)


def _like_value(constants: ScoringConstants, worker: int, partner: int) -> float:
    """l(partner) for worker: nothing for a liked partner, alpha for a neutral one, beta for a disliked one."""
    worker_constants = constants.workers[worker]
    if partner in worker_constants.likes:
        return LIKED_PARTNER
    if partner in worker_constants.dislikes:
        return DISLIKED_PARTNER
    return constants.parameters.neutral_partner * DISLIKED_PARTNER


def workload_penalty(constants: ScoringConstants, assignment: Sequence[int | None]) -> float:
    """
    The normalized workload penalty W*: the sum of av * (assigned hours / av) ** p, scaled by its largest possible
    value (workers with no availability are left out)
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :return: k * W / workload_scale, in [0, k]; 0 if no worker can be assigned anything
    """
    if constants.workload_scale == 0:
        return 0.0
    power = constants.parameters.workload_power
    assigned_hours = _assigned_hours(constants, assignment)
    total = sum(worker.availability * (assigned_hours[index] / worker.availability) ** power
                for index, worker in enumerate(constants.workers) if worker.availability > 0)
    return len(constants.workers) * total / constants.workload_scale


def lower_bound(constants: ScoringConstants, assignment: Sequence[int | None],
                eligible_workers: Collection[int]) -> float:
    """
    A lower bound on the total penalty of every complete schedule that extends a partial one (ADR 0024): the likes
    and rest penalties so far, which filling slots never lowers, and the lowest workload penalty the remaining hours
    could give (workload_lower_bound)
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None for an unfilled slot
    :param eligible_workers: every worker who can still fill some unfilled slot
    :return: a number at most the total penalty of every completion, and at least the partial schedule's own
    """
    parameters = constants.parameters
    return (parameters.likes_weight * likes_penalty(constants, assignment)
            + parameters.workload_weight * workload_lower_bound(constants, assignment, eligible_workers)
            + parameters.rest_weight * rest_penalty(constants, assignment))


def workload_lower_bound(constants: ScoringConstants, assignment: Sequence[int | None],
                         eligible_workers: Collection[int]) -> float:
    """
    The lowest normalized workload penalty any completion of a partial schedule could have. The hours of the unfilled
    slots must go to eligible workers; since each worker's term av * (hours / av) ** p is convex, the total is lowest
    when they top up the least-loaded eligible workers to a common level of hours / av, as water fills a vessel
    (Jensen's inequality). Which worker can take which slot is ignored, so the bound may be lower than reachable.
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :param eligible_workers: every worker who can still fill some unfilled slot
    :return: in [workload_penalty(assignment), k]
    """
    if constants.workload_scale == 0:
        return 0.0
    power = constants.parameters.workload_power
    assigned_hours = _assigned_hours(constants, assignment)
    remaining = sum(constants.slot_hours[slot] for slot, worker in enumerate(assignment) if worker is None)
    fixed = 0.0  # the terms of workers who get no more hours
    pool: list[tuple[float, float, float]] = []  # (hours / av, av, hours) of the workers who may
    for index, worker in enumerate(constants.workers):
        if worker.availability <= 0:
            continue
        if index in eligible_workers:
            pool.append((assigned_hours[index] / worker.availability, worker.availability, assigned_hours[index]))
        else:
            fixed += worker.availability * (assigned_hours[index] / worker.availability) ** power
    pool.sort()
    level = _water_level(pool, remaining)
    filled = sum(availability * max(ratio, level) ** power for ratio, availability, _ in pool)
    return len(constants.workers) * (fixed + filled) / constants.workload_scale


def _water_level(pool: list[tuple[float, float, float]], remaining: float) -> float:
    """
    The common level of hours / av that the remaining hours raise the least-loaded workers of the pool to
    :param pool: (hours / av, av, hours) per worker, sorted by hours / av
    :param remaining: the hours to spread
    :return: the level; workers already above it keep their own
    """
    total_availability = total_hours = 0.0
    for position, (ratio, availability, worker_hours) in enumerate(pool):
        total_availability += availability
        total_hours += worker_hours
        level = (remaining + total_hours) / total_availability
        next_ratio = pool[position + 1][0] if position + 1 < len(pool) else float("inf")
        if level <= next_ratio:
            return level
    return 0.0  # an empty pool: nothing to raise


def _assigned_hours(constants: ScoringConstants, assignment: Sequence[int | None]) -> list[float]:
    """Each worker's total assigned hours."""
    totals = [0.0] * len(constants.workers)
    for slot_index, worker in enumerate(assignment):
        if worker is not None:
            totals[worker] += constants.slot_hours[slot_index]
    return totals


def rest_penalty(constants: ScoringConstants, assignment: Sequence[int | None]) -> float:
    """
    The normalized rest penalty R**: for each worker, the hours by which each rest falls short of gamma times the
    length of the shift before it, divided by the worker's worst possible deficit M_w
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :return: the sum over workers, in [0, k]; workers with M_w = 0 can never have a deficit and count 0
    """
    rest_factor = constants.parameters.rest_factor
    total = 0.0
    for worker, slot_indexes in enumerate(_slots_by_worker(constants, assignment)):
        worst = constants.workers[worker].worst_deficit
        if worst == 0:
            continue
        deficit = 0.0
        # Slots in stable order are sorted by start time, and a worker's slots never overlap, so consecutive slots
        # are consecutive shifts; the last one has no rest after it, and so no deficit.
        for earlier, later in zip(slot_indexes, slot_indexes[1:]):
            rest = hours(constants.slots[later].time.start - constants.slots[earlier].time.end)
            deficit += max(0.0, rest_factor * constants.slot_hours[earlier] - rest)
        total += deficit / worst
    return total


def _slots_by_worker(constants: ScoringConstants, assignment: Sequence[int | None]) -> list[list[int]]:
    """For each worker, the indexes of the slots assigned to them, in stable order."""
    slots: list[list[int]] = [[] for _ in constants.workers]
    for slot_index, worker in enumerate(assignment):
        if worker is not None:
            slots[worker].append(slot_index)
    return slots

