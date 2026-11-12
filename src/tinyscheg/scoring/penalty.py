"""
The penalty score of a (partial) schedule (see docs/explanation/scoring.md): a weighted sum of the likes, workload
and rest penalties, each normalized to [0, k] for k workers. Lower is better, and filling another slot never lowers
it.

An assignment holds a worker index per slot, in stable slot order, or None for a slot that isn't filled yet. Every
penalty is computed from scratch, with sums always taken in the same order (shifts, slots and workers in their stable
order), so the same assignment always gets exactly the same penalty, however it was reached (ADR 0012).
"""
from __future__ import annotations

from collections.abc import Sequence
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
                domains: Sequence[Sequence[int]]) -> float:
    """
    A lower bound on the total penalty of every complete schedule that extends a partial one (ADR 0024): the lowest
    likes penalty the shifts' pairings could still give (likes_lower_bound), the lowest workload penalty the remaining
    hours could give (workload_lower_bound), and the rest penalty so far, which filling slots never lowers. Neither
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
    The lowest normalized likes penalty any completion of a partial schedule could have. In a complete schedule, each
    pair of slots in a shared shift adds both workers' like values of each other, over the shift's other slots; a
    pair with an unfilled slot adds at least the lowest value any workers still in their domains could give
    (choosing each pair's best independently, and even the same worker twice, only lowers the bound)
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :param domains: for each slot, the workers who can still fill it
    :return: in [likes_penalty(assignment), k]; 0 if no shift has more than one slot
    """
    if constants.shared_slots == 0:
        return 0.0
    total = 0.0
    for shift in constants.shifts:
        others = len(shift.slots) - 1
        if others == 0:
            continue
        candidates = [(assignment[slot.index],) if assignment[slot.index] is not None else domains[slot.index]
                      for slot in shift.slots]
        for first in range(len(candidates)):
            for second in range(first + 1, len(candidates)):
                total += min(_like_value(constants, worker, partner) + _like_value(constants, partner, worker)
                             for worker in candidates[first] for partner in candidates[second]) / others
    return len(constants.workers) * total / (DISLIKED_PARTNER * constants.shared_slots)


def workload_lower_bound(constants: ScoringConstants, assignment: Sequence[int | None],
                         domains: Sequence[Sequence[int]]) -> float:
    """
    The lowest normalized workload penalty any completion of a partial schedule could have. The hours of the unfilled
    slots must go to workers in their domains, each worker gaining at most the hours of the unfilled slots they're in
    the domain of. Since each worker's term av * (hours / av) ** p is convex, the total is lowest when the hours top
    up the least-loaded workers to a common level of hours / av, each only up to their cap, as water fills vessels of
    different heights (Jensen's inequality). Which slots overlap is ignored, so the bound may be lower than reachable.
    :param constants: ScoringConstants
    :param assignment: a worker index per slot, or None
    :param domains: for each slot, the workers who can still fill it
    :return: in [workload_penalty(assignment), k]
    """
    if constants.workload_scale == 0:
        return 0.0
    power = constants.parameters.workload_power
    assigned_hours = _assigned_hours(constants, assignment)
    caps = [0.0] * len(constants.workers)
    remaining = 0.0
    for slot, worker in enumerate(assignment):
        if worker is None:
            remaining += constants.slot_hours[slot]
            for candidate in domains[slot]:
                caps[candidate] += constants.slot_hours[slot]
    pool: list[tuple[float, float, float]] = []  # (hours / av, av, highest hours / av) per worker
    for index, worker in enumerate(constants.workers):
        if worker.availability > 0:
            pool.append((assigned_hours[index] / worker.availability, worker.availability,
                         (assigned_hours[index] + caps[index]) / worker.availability))
    level = _water_level(pool, remaining)
    filled = sum(availability * min(max(ratio, level), highest) ** power for ratio, availability, highest in pool)
    return len(constants.workers) * filled / constants.workload_scale


def _water_level(pool: list[tuple[float, float, float]], remaining: float) -> float:
    """
    The common level of hours / av that the remaining hours raise the workers of the pool to, each worker only up to
    their highest; workers already above it keep their own
    :param pool: (hours / av, av, highest hours / av) per worker
    :param remaining: the hours to spread
    :return: the level; 0 if there's nothing to spread
    """
    def spread(level: float) -> float:
        """The hours it takes to raise every worker to the level, within their highest."""
        return sum(availability * (min(max(ratio, level), highest) - ratio) for ratio, availability, highest in pool)

    if remaining <= 0 or not pool:
        return 0.0
    # spread() is piecewise linear and rises between consecutive breakpoints (where a worker starts or stops rising)
    breakpoints = sorted({ratio for ratio, _, _ in pool} | {highest for _, _, highest in pool})
    lower, lower_spread = breakpoints[0], 0.0
    for upper in breakpoints[1:]:
        upper_spread = spread(upper)
        if upper_spread >= remaining:
            return lower + (remaining - lower_spread) * (upper - lower) / (upper_spread - lower_spread)
        lower, lower_spread = upper, upper_spread
    return breakpoints[-1]  # every worker is at their highest: the caps can't take all the hours


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

