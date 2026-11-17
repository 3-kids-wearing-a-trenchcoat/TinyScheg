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
exactly; otherwise T_w widens to the intervals {0}, [u, L], [2u, 2L], ... (L the largest remaining load).

The best mu is found exactly (ADR 0044). LB is concave and piecewise linear in mu, and each evaluation gives both its
value and its slope there, R less the load the per-worker minimizers hand out. Once mu is bracketed between a rising
end and a falling one, the tangent lines at the two ends cross at a height that no LB(mu) exceeds; the next mu tried
is where they cross, and the search stops when the value found reaches that height, which proves it's the highest.

Every value found is a valid bound; it's lowered by a relative ROUNDING_MARGIN, so that rounding can never lift it
above a completion, and the search's result is exactly the same as without it.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from tinyscheg.scoring.constants import integer_power

# Exact combinations of the remaining slot loads are listed up to this many per bound (the counts of every load but
# the most frequent, whose count is then chosen directly); beyond it, the looser intervals are used
MAX_LOAD_COMBINATIONS = 64
# The search for the best mu (ADR 0044). Bracketing: from the water level's marginal cost, mu is multiplied by this
# until LB falls. 2 was measured (2026-11-17: 3-6 evaluations per bound, all certified)
MU_GROWTH = 2.0
# It stops once the value found is within this share of the tangents' crossing, which no LB(mu) is above: far below
# ROUNDING_MARGIN, so the value is the highest up to rounding
OPTIMUM_GAP = 1e-12
# A safeguard only: at most this many evaluations of LB per bound (the best found so far is still a valid bound)
MAX_MU_STEPS = 60
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
    at_zero = 0.0  # LB(0): with mu = 0 nobody takes anything, since each term rises with the worker's load
    for availability, load in zip(availabilities, loads):
        if availability > 0:
            at_zero += _term(power, availability, load, 0.0, 0.0)
    best = _best_over_mu(evaluate, remaining, power * integer_power(level, power - 1), at_zero)
    return best - ROUNDING_MARGIN * abs(best)


def _best_over_mu(evaluate: _Evaluate, remaining: float, start: float, at_zero: float) -> float:
    """
    The highest LB(mu), by tangents (ADR 0044). LB is concave and piecewise linear in mu, with slope R - handed at
    each mu (handed: the load the per-worker minimizers hand out). mu = 0 is a rising end (slope R); the first falling
    end is found by multiplying mu by MU_GROWTH from the start. Then the next mu is where the tangents at the two ends
    cross: no LB(mu) is above that crossing, so the search stops when the value found reaches it; otherwise the mu
    tried replaces the end whose slope has its sign
    :param evaluate: (LB(mu), the load handed out) for a mu
    :param remaining: R
    :param start: the first mu tried, the water level's marginal cost
    :param at_zero: LB(0)
    :return: the highest value found: LB's maximum up to OPTIMUM_GAP, unless MAX_MU_STEPS ran out first or no mu
    hands out all of R (then no completion exists); always a valid bound
    """
    best = at_zero
    if start <= 0:
        return best
    low_mu, low_value, low_slope = 0.0, at_zero, remaining
    mu, steps = start, 0
    while True:  # bracketing: until the slope turns negative
        value, handed = evaluate(mu)
        steps += 1
        if value > best:
            best = value
        slope = remaining - handed
        if abs(slope) <= LOAD_TOLERANCE:  # a mu at which the slope is 0 is LB's highest point
            return best
        if slope < 0:
            break
        if steps >= MAX_MU_STEPS:
            return best
        low_mu, low_value, low_slope = mu, value, slope
        mu *= MU_GROWTH
    high_mu, high_value, high_slope = mu, value, slope
    while steps < MAX_MU_STEPS:
        # the tangents low_value + low_slope * (mu - low_mu) and high_value + high_slope * (mu - high_mu) cross here
        mu = (high_value - low_value + low_slope * low_mu - high_slope * high_mu) / (low_slope - high_slope)
        ceiling = low_value + low_slope * (mu - low_mu)
        if not low_mu < mu < high_mu:  # rounding: the bracket can't narrow any further
            break
        value, handed = evaluate(mu)
        steps += 1
        if value > best:
            best = value
        slope = remaining - handed
        if ceiling - best <= OPTIMUM_GAP * abs(best) or abs(slope) <= LOAD_TOLERANCE:
            break
        if slope > 0:
            low_mu, low_value, low_slope = mu, value, slope
        else:
            high_mu, high_value, high_slope = mu, value, slope
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
    # what doesn't change with mu, per worker with some availability: (av, x, cap, n_w, cap with the tolerance)
    workers = [(availability, load, cap, most_slots, cap + LOAD_TOLERANCE)
               for availability, load, cap, most_slots in zip(availabilities, loads, caps, counts) if availability > 0]
    floor = math.floor

    def evaluate(mu: float) -> tuple[float, float]:
        """
        LB(mu) and the load handed out, over the exact combinations. This is most of the search's time (2026-11-15),
        so it's written for speed: plain comparisons rather than min and max, each candidate's term computed in place
        (as _term does, with the same arithmetic, so the same results), and the second candidate only where it
        differs from the first.
        """
        value, handed = mu * remaining, 0.0
        for availability, load, cap, most_slots, cap_limit in workers:
            ideal = _ideal_extra(mu, power, availability, load)
            best, best_extra = _term(power, availability, load, 0.0, mu), 0.0
            for partial, used in combinations:
                if used > most_slots or partial > cap_limit:
                    continue
                most = int((cap - partial) / free_load + LOAD_TOLERANCE)  # the free load's count: at most this,
                if most > most_slots - used:                              # the slots left and the count remaining
                    most = most_slots - used
                if most > free_count:
                    most = free_count
                if most < 0:
                    most = 0
                below = floor((ideal - partial) / free_load)  # the count just below the ideal, within [0, most]
                if below < 0:
                    below = 0
                elif below > most:
                    below = most
                extra = partial + below * free_load
                total = load + extra
                term = (total * total / availability if power == 2
                        else availability * integer_power(total / availability, power)) - mu * extra
                if term < best:
                    best, best_extra = term, extra
                if below < most:  # and the count just above it
                    extra = partial + (below + 1) * free_load
                    total = load + extra
                    term = (total * total / availability if power == 2
                            else availability * integer_power(total / availability, power)) - mu * extra
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
