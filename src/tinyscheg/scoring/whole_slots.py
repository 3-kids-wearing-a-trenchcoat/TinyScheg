"""
The workload penalty's lower bound in whole slots (ADR 0040). The water-filling bound (penalty.workload_lower_bound,
ADR 0024) spreads the remaining load as finely as it likes; in a real schedule each slot goes whole to one worker,
which is where almost all of that bound's slack came from. This one keeps the slots whole, by Lagrangian relaxation
of "all the remaining load R is handed out":

For any mu, and any completion giving each worker w an extra load z_w (the z_w adding up to R),

    sum_w f_w(z_w) = mu * R + sum_w (f_w(z_w) - mu * z_w) >= mu * R + sum_w min over z in T_w of (f_w(z) - mu * z)

where f_w(z) = av_w * ((x_w + z) / av_w) ** p is the worker's term with x_w already assigned, and T_w is any set
holding every extra load the worker could get. So the right-hand side, LB(mu), is a lower bound for every mu, and
each worker's minimum is found on their own. Two kinds of sets T_w, chosen per run (ADR 0047):
* global (whole_slot_bound, ADR 0040): whole numbers of the remaining slots of each load, no more of each load than
  remain, at most n_w = cap_w / u slots in all (u the smallest remaining load) and at most cap_w in all (cap_w the
  load of the unfilled slots in the worker's domains); listed exactly with few combinations of loads, otherwise
  widened to the intervals {0}, [u, L], [2u, 2L], ... (L the largest remaining load);
* each worker's own (own_whole_slot_bound, ADR 0046): whole numbers of the unfilled slots of each load in the
  worker's own domain, no more of each load than they're in the domain of; listed exactly with few combinations,
  otherwise the intervals {0}, [u_w, L_w], [2 u_w, 2 L_w], ... up to the number of slots in their domain, cut at cap_w
  (u_w and L_w the smallest and largest load among those slots). They lie within the global sets, so the bound is
  never lower, but keeping each worker's counts costs more.

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

# Exact combinations of the slot loads are listed up to this many (per bound with the global sets, per worker with
# their own; the counts of every load but the most frequent, whose count is then chosen directly); beyond it, the
# looser intervals are used
MAX_LOAD_COMBINATIONS = 64
# Each worker's combinations depend only on their counts of slots per load, so they're kept for reuse: at most this
# many different sets of counts at a time (a search meets far fewer); beyond it, the cache starts afresh
COMBINATIONS_CACHE_SIZE = 4096
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


# One worker's sets T_w, as the evaluator uses them: None (no slot in their domain), ("exact", combinations of the
# loads but the most frequent as (load, slots), the most frequent load, its count), or ("intervals", the smallest
# load, the largest, the number of slots)
_Sets = tuple | None


def whole_slot_bound(power: int, availabilities: Sequence[float], loads: Sequence[float], caps: Sequence[float],
                     remaining: float, classes: Sequence[tuple[float, int]], level: float) -> float | None:
    """
    A lower bound on the sum of av * (load / av) ** p over every completion, handing out the unfilled slots whole,
    with the global sets (ADR 0040)
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


def own_whole_slot_bound(power: int, availabilities: Sequence[float], loads: Sequence[float], caps: Sequence[float],
                         remaining: float, own_counts: Sequence[Sequence[int]], load_classes: tuple[float, ...],
                         level: float) -> float | None:
    """
    A lower bound on the sum of av * (load / av) ** p over every completion, handing out the unfilled slots whole,
    each worker's sets from their own domain (ADR 0046)
    :param power: p, the workload power (at least 2)
    :param availabilities: av per worker, in worker order
    :param loads: each worker's load so far
    :param caps: the most extra load each worker could get: the loads of the unfilled slots in their domains
    :param remaining: R, the load of the unfilled slots
    :param own_counts: per worker, how many unfilled slots in their domain have each load of load_classes
    :param load_classes: the schedule's distinct slot loads, ascending (ScoringConstants.load_classes)
    :param level: the water level of the water-filling bound, whose marginal cost is where mu's search starts
    :return: the bound, before normalizing and already lowered by ROUNDING_MARGIN; None if it doesn't apply (nothing
    left to fill, or a worker with no availability who could take load, whose share the penalty doesn't count)
    """
    if remaining <= LOAD_TOLERANCE:
        return None
    if any(availability <= 0 and cap > LOAD_TOLERANCE for availability, cap in zip(availabilities, caps)):
        return None
    evaluate, at_zero = _evaluator(power, availabilities, loads, caps, remaining, own_counts, load_classes)
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


class _SetsCache:
    """
    Each worker's sets T_w by their counts of unfilled slots per load (step 5 of Phase 11): the same counts always
    give the same sets, so they're built once. A plain dict keyed by the counts themselves, rather than
    functools.lru_cache keyed by the (load, count) pairs: PyPy's lru_cache is written in Python, and building and
    hashing the pairs at every bound cost as much again (2026-11-17: the search 11-32% faster on PyPy). The sets
    also depend on the loads the counts are of, and on MAX_LOAD_COMBINATIONS, so it's kept for one of each at a time.
    """

    def __init__(self) -> None:
        self.loads: tuple[float, ...] | None = None
        self.most_combinations = -1
        self.by_counts: dict[tuple[int, ...], _Sets] = {}

    def for_loads(self, load_classes: tuple[float, ...], most_combinations: int) -> dict[tuple[int, ...], _Sets]:
        """
        The sets built so far for these loads and this limit, as a dict from a worker's counts to their sets; empty
        when either changed, or when it holds more than COMBINATIONS_CACHE_SIZE
        :param load_classes: the schedule's distinct slot loads, ascending
        :param most_combinations: MAX_LOAD_COMBINATIONS
        :return: the dict, to look up in and add to
        """
        if (load_classes != self.loads or most_combinations != self.most_combinations
                or len(self.by_counts) > COMBINATIONS_CACHE_SIZE):
            self.loads, self.most_combinations, self.by_counts = load_classes, most_combinations, {}
        return self.by_counts


_SETS_CACHE = _SetsCache()
_NOT_BUILT = object()  # what the cache gives for counts whose sets aren't built yet


def _own_sets(classes: tuple[tuple[float, int], ...], most_combinations: int) -> _Sets:
    """
    One worker's sets T_w, from their counts of unfilled slots per load
    :param classes: (load, count) of the slots in their domain, ascending, every count at least 1
    :param most_combinations: MAX_LOAD_COMBINATIONS
    :return: the sets, as _Sets describes them
    """
    if not classes:
        return None
    free = max(range(len(classes)), key=lambda index: classes[index][1])  # the first of the most frequent
    size = 1
    for index, (_, count) in enumerate(classes):
        if index != free:
            size *= count + 1
    if size > most_combinations:
        return "intervals", classes[0][0], classes[-1][0], sum(count for _, count in classes)
    combinations = [(0.0, 0)]  # (the load, the number of slots) of each combination of the listed loads
    for index, (load, count) in enumerate(classes):
        if index != free:
            combinations = [(total + taken * load, used + taken)
                            for total, used in combinations for taken in range(count + 1)]
    return "exact", tuple(combinations), classes[free][0], classes[free][1]


def _evaluator(power: int, availabilities: Sequence[float], loads: Sequence[float], caps: Sequence[float],
               remaining: float, own_counts: Sequence[Sequence[int]], load_classes: tuple[float, ...]
               ) -> tuple[_Evaluate, float]:
    """
    LB(mu) over each worker's own sets, and LB(0)
    :param power: p
    :param availabilities: av per worker
    :param loads: each worker's load so far
    :param caps: each worker's cap
    :param remaining: R
    :param own_counts: per worker, how many unfilled slots in their domain have each load of load_classes
    :param load_classes: the schedule's distinct slot loads, ascending
    :return: (evaluate(mu), LB(0)); with mu = 0 nobody takes anything, since each term rises with the worker's load
    """
    workers = []  # (av, x, cap, sets) per worker with some availability
    at_zero = 0.0
    most_combinations = MAX_LOAD_COMBINATIONS
    built = _SETS_CACHE.for_loads(load_classes, most_combinations)
    for availability, load, cap, counts in zip(availabilities, loads, caps, own_counts):
        if availability > 0:
            key = tuple(counts)
            sets = built.get(key, _NOT_BUILT)  # one lookup where the sets are built already, as they mostly are
            if sets is _NOT_BUILT:
                sets = built[key] = _own_sets(tuple((slot_load, count) for slot_load, count in zip(load_classes, counts)
                                                    if count > 0), most_combinations)
            workers.append((availability, load, cap, sets))
            at_zero += _term(power, availability, load, 0.0, 0.0)
    floor = math.floor

    def evaluate(mu: float) -> tuple[float, float]:
        """
        LB(mu) and the load handed out. This is most of the search's time (2026-11-15), so it's written for speed:
        plain comparisons rather than min and max, each candidate's term computed in place (as _term does, with the
        same arithmetic, so the same results), and the second candidate only where it differs from the first.
        """
        value, handed = mu * remaining, 0.0
        for availability, load, cap, sets in workers:
            best, best_extra = _term(power, availability, load, 0.0, mu), 0.0
            if sets is None:
                value += best
                continue
            ideal = _ideal_extra(mu, power, availability, load)
            if sets[0] == "exact":
                _, combinations, free_load, free_count = sets
                for partial, _ in combinations:
                    # the most frequent load's count just below the ideal, within [0, its count]: the term is convex
                    # in it, so one of the two around the ideal is best
                    below = floor((ideal - partial) / free_load)
                    if below < 0:
                        below = 0
                    elif below > free_count:
                        below = free_count
                    extra = partial + below * free_load
                    total = load + extra
                    term = (total * total / availability if power == 2
                            else availability * integer_power(total / availability, power)) - mu * extra
                    if term < best:
                        best, best_extra = term, extra
                    if below < free_count:  # and the count just above it
                        extra += free_load
                        total = load + extra
                        term = (total * total / availability if power == 2
                                else availability * integer_power(total / availability, power)) - mu * extra
                        if term < best:
                            best, best_extra = term, extra
            else:
                best, best_extra = _interval_minimum(power, availability, load, cap, sets, mu, ideal)
            value += best
            handed += best_extra
        return value, handed

    return evaluate, at_zero


def _interval_minimum(power: int, availability: float, load: float, cap: float, sets: tuple, mu: float,
                      ideal: float) -> tuple[float, float]:
    """
    A worker's lowest f(z) - mu * z over the intervals {0}, [u, L], ..., [n u, n L], cut at the cap: j slots carry
    between j times the smallest and j times the largest load. The term is convex, so its lowest point on them is the
    ideal extra load if that falls in one, or else an end of the gap it falls in
    :param power: p
    :param availability: av
    :param load: x, the worker's load so far
    :param cap: their cap
    :param sets: ("intervals", u, L, n)
    :param mu: float
    :param ideal: the ideal extra load (_ideal_extra)
    :return: (the lowest term, its extra load)
    """
    _, smallest, largest, most_slots = sets
    ideal = min(max(ideal, 0.0), cap)
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
    return best, best_extra


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
