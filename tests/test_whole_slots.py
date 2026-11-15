"""Tests for tinyscheg.scoring.whole_slots, the workload bound in whole slots (ADR 0040), against brute force."""
import random
from itertools import product

import pytest

from test_search import constants_of, small_inputs
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_best_schedule
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.scoring import penalty, whole_slots
from tinyscheg.scoring.constants import integer_power
from tinyscheg.scoring.penalty import _water_level
from tinyscheg.scoring.whole_slots import whole_slot_bound

CASES = 300                 # random cases compared with brute force, per power and set of loads
MOST_WORKERS = 4
MOST_SLOTS = 6              # 4 ** 6 completions at most, so brute force stays quick
LOAD_CHOICES = (1.0, 1.5, 2.5, 4.0)
CLOSE = 1e-9                # how close the bound may come to brute force's minimum without being above it


def random_case(rng: random.Random) -> tuple[list[float], list[float], list[float], list[list[int]]]:
    """
    A random partial schedule's workload: availabilities, loads so far, and the unfilled slots' loads and domains
    :param rng: random.Random
    :return: (availabilities, loads, slot loads, slot domains)
    """
    workers = rng.randint(2, MOST_WORKERS)
    availabilities = [rng.choice((8.0, 12.0, 24.0)) for _ in range(workers)]
    loads = [rng.choice((0.0, 0.0, 1.0, 2.5, 4.0)) for _ in range(workers)]
    kinds = rng.sample(LOAD_CHOICES, rng.randint(1, 3))
    slots = [rng.choice(kinds) for _ in range(rng.randint(1, MOST_SLOTS))]
    domains = [rng.sample(range(workers), rng.randint(1, workers)) for _ in slots]
    return availabilities, loads, slots, domains


def brute_force(power: int, availabilities: list[float], loads: list[float], slots: list[float],
                domains: list[list[int]]) -> float:
    """The lowest sum of av * (load / av) ** p over every way of giving each slot to a worker in its domain."""
    best = float("inf")
    for chosen in product(*domains):
        totals = list(loads)
        for slot_load, worker in zip(slots, chosen):
            totals[worker] += slot_load
        best = min(best, sum(av * integer_power(total / av, power) for av, total in zip(availabilities, totals)))
    return best


def bounds(power: int, availabilities: list[float], loads: list[float], slots: list[float],
           domains: list[list[int]]) -> tuple[float, float | None]:
    """(the water-filling bound, the whole-slot bound), before normalizing, as penalty.workload_bound_total gets
    them."""
    caps = [0.0] * len(availabilities)
    for slot_load, domain in zip(slots, domains):
        for worker in domain:
            caps[worker] += slot_load
    remaining = sum(slots)
    pool = [(load / av, av, (load + cap) / av) for av, load, cap in zip(availabilities, loads, caps)]
    level = _water_level(pool, remaining)
    filled = sum(av * integer_power(min(max(ratio, level), highest), power) for ratio, av, highest in pool)
    classes = [(load, slots.count(load)) for load in sorted(set(slots))]
    return filled, whole_slot_bound(power, availabilities, loads, caps, remaining, classes, level)


@pytest.mark.parametrize("power", [2, 3])
@pytest.mark.parametrize("most_combinations", [whole_slots.MAX_LOAD_COMBINATIONS, 0])  # exact, then intervals only
def test_the_bound_is_never_above_the_best_whole_slot_completion(power: int, most_combinations: int,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(whole_slots, "MAX_LOAD_COMBINATIONS", most_combinations)
    rng = random.Random(power)
    tighter = 0
    for _ in range(CASES):
        case = random_case(rng)
        best = brute_force(power, *case)
        filled, whole = bounds(power, *case)
        assert whole is not None and whole <= best + CLOSE
        tighter += whole > filled + CLOSE
    assert tighter > CASES / 4  # and it means something: it's often above the water-filling bound


def test_one_slot_two_workers_by_hand() -> None:
    # One slot of load 4 for two equally available workers with nothing yet. Water-filling gives each half:
    # 2 * 8 * (2 / 8) ** 2 = 1. Whole, one of them gets it all: 8 * (4 / 8) ** 2 = 2, and the bound finds it.
    filled, whole = bounds(2, [8.0, 8.0], [0.0, 0.0], [4.0], [[0, 1]])
    assert filled == pytest.approx(1.0)
    assert whole == pytest.approx(2.0)


def test_no_bound_when_a_worker_with_no_availability_could_take_load() -> None:
    # their term isn't counted, so load they take is free: the sets would have to allow for it
    assert whole_slot_bound(2, [0.0, 8.0], [0.0, 0.0], [4.0, 4.0], 4.0, [(4.0, 1)], 0.5) is None


def test_no_bound_with_nothing_left_to_fill() -> None:
    assert whole_slot_bound(2, [8.0, 8.0], [2.0, 0.0], [0.0, 0.0], 0.0, [], 0.0) is None


@pytest.mark.parametrize("schedule_input", small_inputs())
def test_the_search_finds_the_same_schedule_with_and_without_it(schedule_input: ScheduleInput,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR 0040: a valid bound only cuts branches that can't beat the pocket, so the result is exactly the same
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    with_it = find_best_schedule(problem, constants)
    monkeypatch.setattr(penalty, "whole_slot_bound", lambda *arguments: None)
    without_it = find_best_schedule(problem, constants)
    assert (with_it.assignment, with_it.penalty) == (without_it.assignment, without_it.penalty)
    assert with_it.nodes <= without_it.nodes
