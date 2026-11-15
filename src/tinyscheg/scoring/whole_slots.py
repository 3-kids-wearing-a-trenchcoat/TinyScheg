"""
The workload penalty's lower bound in whole slots (ADR 0040). The water-filling bound (penalty.workload_lower_bound,
ADR 0024) spreads the remaining load as finely as it likes; in a real schedule each slot goes whole to one worker,
which is where almost all of that bound's slack came from. This one keeps the slots whole, by Lagrangian relaxation
of "all the remaining load R is handed out":

For any mu, and any completion giving each worker w an extra load z_w (the z_w adding up to R),

    sum_w f_w(z_w) = mu * R + sum_w (f_w(z_w) - mu * z_w) >= mu * R + sum_w min over z in T_w of (f_w(z) - mu * z)

where f_w(z) = av_w * ((x_w + z) / av_w) ** p is the worker's term with x_w already assigned, and T_w is any set
holding every extra load the worker could get. So the right-hand side, LB(mu), is a lower bound for every mu, and
each worker's minimum is found on their own. T_w: whole numbers of the remaining slots of each load, no more of each
load than remain, at most n_w = cap_w / u slots in all (u the smallest remaining load) and at most cap_w in all
(cap_w the load of the unfilled slots in the worker's domains). With few combinations of loads they're listed
exactly; otherwise T_w widens to the intervals {0}, [u, L], [2u, 2L], ... (L the largest remaining load). The best
mu is searched near the water level's marginal cost, by bisection on how much load the minimizers hand out.

Every value found is a valid bound, however few values of mu are tried; it's lowered by a relative ROUNDING_MARGIN,
so that rounding can never lift it above a completion, and the search's result is exactly the same as without it.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from tinyscheg.scoring.constants import integer_power

# Exact combinations of the remaining slot loads are listed up to this many per bound (the counts of every load but
# the most frequent, whose count is then chosen directly); beyond it, the looser intervals are used
MAX_LOAD_COMBINATIONS = 64
# The search for the best mu: at most this many steps to bracket it, each moving mu by MU_GROWTH times, then this
# many halvings of the bracket. Every value tried is a valid bound, so fewer steps only loosen it; 3 was fastest on
# the benchmarks (2026-11-15: 2 visited nearly twice the nodes, 6 cost more time than the nodes it saved)
MU_STEPS = 3
MU_GROWTH = 1.5
# Loads (in hours) within this of each other count as equal: so a count or cap that rounding put a hair short of a
# whole number of slots still allows it, which only widens the sets
LOAD_TOLERANCE = 1e-9
# The bound is lowered by this share of itself, far more than its rounding error and far less than any difference
# between schedules worth telling apart
ROUNDING_MARGIN = 1e-9

# evaluate(mu) -> (LB(mu), the load the per-worker minimizers hand out in all)
_Evaluate = Callable[[float], tuple[float, float]]


def whole_slot_bound(power: int, availabilities: Sequence[float], loads: Sequence[float], caps: Sequence[float],
                     remaining: float, classes: Sequence[tuple[float, int]], level: float) -> float | None:
    """
    A lower bound on the sum of av * (load / av) ** p over every completion, handing out the unfilled slots whole
    :param power: p, the workload power (at least 2)
    :param availabilities: av per worker, in worker order
    :param loads: each worker's load so far
    :param caps: the most extra load each worker could get: the loads of the unfilled slots in their domains
    :param remaining: R, the load of the unfilled slots
    :param classes: (load, how many unfilled slots have it) for every load at least one unfilled slot has, ascending
    :param level: the water level of the water-filling bound, whose marginal cost is where mu's search starts
    :return: the bound, before normalizing and already lowered by ROUNDING_MARGIN; None if it doesn't apply (nothing
    left to fill, or a worker with no availability who could take load, whose share the penalty doesn't count)
    """
    if not classes or classes[0][0] <= 0:
        return None
    if any(availability <= 0 and cap > LOAD_TOLERANCE for availability, cap in zip(availabilities, caps)):
        return None
    smallest = classes[0][0]
    counts = [int(cap / smallest + LOAD_TOLERANCE) for cap in caps]  # n_w: each slot carries at least u
    evaluate = _exact_evaluator(power, availabilities, loads, caps, counts, remaining, classes)
    if evaluate is None:
        evaluate = _interval_evaluator(power, availabilities, loads, caps, counts, remaining, smallest, classes[-1][0])
    best = _best_over_mu(evaluate, remaining, power * integer_power(level, power - 1))
    return best - ROUNDING_MARGIN * abs(best)


def _best_over_mu(evaluate: _Evaluate, remaining: float, start: float) -> float:
    """
    The highest LB(mu) found: LB is concave in mu, and rises while the minimizers hand out less than the remaining
    load (more mu makes load cheaper to take), so mu is bracketed from the start, then bisected
    :param evaluate: (LB(mu), the load handed out) for a mu
    :param remaining: R
    :param start: the first mu, at least 0
    :return: the highest value found; it stops early at a mu whose minimizers hand out exactly R, where LB is highest
    """
    best, handed = evaluate(start)
    if start <= 0 or abs(handed - remaining) <= LOAD_TOLERANCE:
        return best
    rising = handed < remaining
    low = high = start
    for _ in range(MU_STEPS):
        probe = high * MU_GROWTH if rising else low / MU_GROWTH
        value, handed = evaluate(probe)
        best = max(best, value)
        if abs(handed - remaining) <= LOAD_TOLERANCE:
            return best
        if rising:
            low, high = high, probe
            if handed > remaining:
                break
        else:
            low, high = probe, low
            if handed < remaining:
                break
    for _ in range(MU_STEPS):
        middle = (low + high) / 2
        value, handed = evaluate(middle)
        best = max(best, value)
        if abs(handed - remaining) <= LOAD_TOLERANCE:
            return best
        if handed < remaining:
            low = middle
        else:
            high = middle
    return best


def _ideal_extra(mu: float, power: int, availability: float, load: float) -> float:
    """
    The extra load at which a worker's f(z) - mu * z would be lowest if any amount could be given: where the
    marginal cost p * ((x + z) / av) ** (p - 1) equals mu. Only which whole loads are tried depends on it
    :param mu: float, at least 0
    :param power: p
    :param availability: av
    :param load: x, the worker's load so far
    :return: z, possibly negative or beyond the worker's cap
    """
    root = mu / power if power == 2 else (mu / power) ** (1 / (power - 1))
    return availability * root - load


def _term(power: int, availability: float, load: float, extra: float, mu: float) -> float:
    """
    A worker's f(z) - mu * z: their workload term with the extra load z, less mu for each unit of it. The default
    power, 2, is written out: calling integer_power here took about 40% of the search's time (2026-11-15)
    :param power: p
    :param availability: av
    :param load: x, the worker's load so far
    :param extra: z
    :param mu: float
    :return: av * ((x + z) / av) ** p - mu * z
    """
    total = load + extra
    if power == 2:
        return total * total / availability - mu * extra
    return availability * integer_power(total / availability, power) - mu * extra


def _exact_evaluator(power: int, availabilities: Sequence[float], loads: Sequence[float], caps: Sequence[float],
                     counts: Sequence[int], remaining: float, classes: Sequence[tuple[float, int]]
                     ) -> _Evaluate | None:
    """
    LB(mu) with T_w the exact combinations of the remaining slot loads: the counts of every load but the most
    frequent are listed; for each, the most frequent load's count is the whole number nearest the ideal extra load
    (the term is convex in it, so one of the two around it is best)
    :param power: p
    :param availabilities: av per worker
    :param loads: each worker's load so far
    :param caps: each worker's cap
    :param counts: n_w, the most slots each worker could get
    :param remaining: R
    :param classes: (load, count) per remaining load, ascending
    :return: evaluate(mu), or None if there'd be more than MAX_LOAD_COMBINATIONS combinations
    """
    free = max(range(len(classes)), key=lambda index: classes[index][1])  # the first of the most frequent
    size = 1
    for index, (_, count) in enumerate(classes):
        if index != free:
            size *= count + 1
    if size > MAX_LOAD_COMBINATIONS:
        return None
    combinations = [(0.0, 0)]  # (the load, the number of slots) of each combination of the listed loads
    for index, (load, count) in enumerate(classes):
        if index != free:
            combinations = [(total + taken * load, used + taken)
                            for total, used in combinations for taken in range(count + 1)]
    free_load, free_count = classes[free]

    def evaluate(mu: float) -> tuple[float, float]:
        """LB(mu) and the load handed out, over the exact combinations."""
        value, handed = mu * remaining, 0.0
        for availability, load, cap, most_slots in zip(availabilities, loads, caps, counts):
            if availability <= 0:
                continue
            ideal = _ideal_extra(mu, power, availability, load)
            best, best_extra = _term(power, availability, load, 0.0, mu), 0.0
            for partial, used in combinations:
                if used > most_slots or partial > cap + LOAD_TOLERANCE:
                    continue
                most = max(0, min(free_count, most_slots - used, int((cap - partial) / free_load + LOAD_TOLERANCE)))
                below = min(max(math.floor((ideal - partial) / free_load), 0), most)
                for taken in (below, min(below + 1, most)):
                    extra = partial + taken * free_load
                    term = _term(power, availability, load, extra, mu)
                    if term < best:
                        best, best_extra = term, extra
            value += best
            handed += best_extra
        return value, handed

    return evaluate


def _interval_evaluator(power: int, availabilities: Sequence[float], loads: Sequence[float], caps: Sequence[float],
                        counts: Sequence[int], remaining: float, smallest: float, largest: float) -> _Evaluate:
    """
    LB(mu) with T_w the intervals {0}, [u, L], ..., [n_w u, n_w L], cut at the cap: j slots carry between j times the
    smallest and j times the largest remaining load. The term is convex, so its lowest point on them is the ideal
    extra load if that falls in one, or else an end of the gap it falls in
    :param power: p
    :param availabilities: av per worker
    :param loads: each worker's load so far
    :param caps: each worker's cap
    :param counts: n_w, the most slots each worker could get
    :param remaining: R
    :param smallest: u, the smallest remaining load
    :param largest: L, the largest remaining load
    :return: evaluate(mu)
    """
    def evaluate(mu: float) -> tuple[float, float]:
        """LB(mu) and the load handed out, over the intervals."""
        value, handed = mu * remaining, 0.0
        for availability, load, cap, most_slots in zip(availabilities, loads, caps, counts):
            if availability <= 0:
                continue
            if most_slots <= 0 or cap + LOAD_TOLERANCE < smallest:
                value += _term(power, availability, load, 0.0, mu)
                continue
            ideal = min(max(_ideal_extra(mu, power, availability, load), 0.0), cap)
            slots = min(int(ideal // smallest), most_slots)  # the last interval starting at or below the ideal
            if slots >= 1 and ideal <= slots * largest:
                candidates = [ideal]  # inside [slots * u, slots * L]
            else:
                candidates = [min(slots * largest, cap) if slots >= 1 else 0.0]  # the gap's lower end
                if slots + 1 <= most_slots and (slots + 1) * smallest <= cap + LOAD_TOLERANCE:
                    candidates.append((slots + 1) * smallest)  # and its upper end
            best, best_extra = math.inf, 0.0
            for extra in candidates:
                term = _term(power, availability, load, extra, mu)
                if term < best:
                    best, best_extra = term, extra
            value += best
            handed += best_extra
        return value, handed

    return evaluate
