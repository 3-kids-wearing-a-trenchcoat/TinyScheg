"""Tests for tinyscheg.scoring.penalty."""
import dataclasses
import datetime as dt
import pathlib
import random
from itertools import product

import pytest

from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, ScoringParameters, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.constants import ScoringConstants, build_constants
from tinyscheg.scoring.penalty import _water_level, likes_penalty, rest_penalty, score, workload_penalty
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"
ALPHA = 1 / 3  # the default neutral partner, relative to a disliked one (beta = 1)


def constants_for(workers: list[Worker], roles: dict[str, int], length: int, period_hours: int,
                  min_rest: int = 0, parameters: ScoringParameters = ScoringParameters()) -> ScoringConstants:
    """The scoring constants of a one-post input: shifts of `length` hours over the first period_hours of 2025."""
    start = dt.datetime(2025, 1, 1)
    period = DateTimeRange(start, start + dt.timedelta(hours=period_hours))
    post = Post("post", ShiftRules(dt.timedelta(hours=length), tuple(roles.items())))
    schedule_input = ScheduleInput(Settings(period, dt.timedelta(hours=min_rest), parameters), tuple(workers),
                                   (post,))
    problem = build_problem(schedule_input)
    return build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots, problem.domains)


# --- likes ---

def test_likes_in_a_two_worker_shift() -> None:
    workers = [Worker("Anne", likes=frozenset({"Bob"})), Worker("Bob"), Worker("Cy", dislikes=frozenset({"Anne"}))]
    constants = constants_for(workers, {"any": 2}, 4, 4)  # one shift of two slots
    # flat, in units of a disliked partner (ADR 0032): Anne likes Bob (0); Bob is neutral about Anne (alpha)
    assert likes_penalty(constants, [0, 1]) == pytest.approx(ALPHA)
    # Anne is neutral about Cy (alpha); Cy dislikes Anne (beta = 1)
    assert likes_penalty(constants, [0, 2]) == pytest.approx(ALPHA + 1)
    assert likes_penalty(constants, [0, None]) == 0  # nobody to share the shift with yet


def test_likes_are_averaged_over_the_other_slots() -> None:
    workers = [Worker("Anne", likes=frozenset({"Bob"}), dislikes=frozenset({"Cy"})), Worker("Bob"), Worker("Cy")]
    constants = constants_for(workers, {"any": 3}, 4, 4)  # one shift of three slots
    anne = (0 + 1) / 2
    bob = cy = (ALPHA + ALPHA) / 2
    assert likes_penalty(constants, [0, 1, 2]) == pytest.approx(anne + bob + cy)


def test_single_slot_shifts_have_no_likes_penalty() -> None:
    constants = constants_for([Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob")], {"any": 1}, 4, 8)
    assert likes_penalty(constants, [0, 1]) == 0


# --- workload ---

def test_spreading_work_beats_concentrating_it() -> None:
    # two 4-hour shifts back to back; each worker is available for 8 hours and could work both
    constants = constants_for([Worker("Anne"), Worker("Bob")], {"any": 1}, 4, 8)
    # in workload units (ADR 0032): one average 4-hour slot for a worker available 8 hours, 4 ** 2 / 8 = 2
    assert constants.workload_unit == 2
    assert workload_penalty(constants, [0, 0]) == pytest.approx(8 * (8 / 8) ** 2 / 2)                 # 4
    assert workload_penalty(constants, [0, 1]) == pytest.approx(2 * 8 * (4 / 8) ** 2 / 2)             # 2
    assert workload_penalty(constants, [None, None]) == 0


def test_workload_is_relative_to_availability() -> None:
    # Bob is away for the first 4 hours: giving him the second shift is fair, giving it to Anne isn't
    bob = Worker("Bob", unavailable=(DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 4)),))
    constants = constants_for([Worker("Anne"), bob], {"any": 1}, 4, 8)
    assert workload_penalty(constants, [0, 1]) < workload_penalty(constants, [0, 0])


def test_higher_power_leans_harder_on_the_most_loaded() -> None:
    workers = [Worker("Anne"), Worker("Bob")]
    square = constants_for(workers, {"any": 1}, 4, 8)
    cube = constants_for(workers, {"any": 1}, 4, 8, parameters=ScoringParameters(workload_power=3))
    gap_square = workload_penalty(square, [0, 0]) - workload_penalty(square, [0, 1])
    gap_cube = workload_penalty(cube, [0, 0]) - workload_penalty(cube, [0, 1])
    assert gap_cube > gap_square


# --- rest ---

def test_rest_deficit_relative_to_the_worst_case() -> None:
    # 4-hour shifts at 0, 4, 8 and 12 with 2 hours' minimum rest; with a rest factor of 3, the target after a 4-hour
    # shift is 12 hours. The worst Anne could do is 0-4 then 8-12 (4 hours' rest, 8 short), so M_w = 8.
    parameters = ScoringParameters(rest_factor=3)
    constants = constants_for([Worker("Anne")], {"any": 1}, 4, 16, min_rest=2, parameters=parameters)
    assert constants.workers[0].worst_deficit == 8
    assert constants.rest_unit == 8  # the mean worst deficit, Anne's own: so her hours short count as hours
    assert rest_penalty(constants, [0, None, 0, None]) == pytest.approx(8)
    assert rest_penalty(constants, [0, None, None, 0]) == pytest.approx(4)  # 8 hours' rest, 4 short
    assert rest_penalty(constants, [0, None, None, None]) == 0


def test_no_rest_penalty_when_the_minimum_rest_meets_the_target() -> None:
    parameters = ScoringParameters(rest_factor=1)  # the target after a 4-hour shift is 4 hours
    constants = constants_for([Worker("Anne")], {"any": 1}, 4, 16, min_rest=4, parameters=parameters)
    assert constants.workers[0].worst_deficit == 0
    assert rest_penalty(constants, [0, None, 0, None]) == 0


# --- the total ---

def test_total_is_the_weighted_sum() -> None:
    workers = [Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob")]
    constants = constants_for(workers, {"any": 2}, 4, 12, min_rest=4)
    assignment = [0, 1, None, None, 0, 1]
    penalty = score(constants, assignment)
    assert penalty.likes == likes_penalty(constants, assignment)
    assert penalty.workload == workload_penalty(constants, assignment)
    assert penalty.rest == rest_penalty(constants, assignment)
    parameters = constants.parameters
    assert penalty.total == pytest.approx(parameters.likes_weight * penalty.likes
                                          + parameters.workload_weight * penalty.workload
                                          + parameters.rest_weight * penalty.rest)


def test_a_zero_weight_ignores_that_part() -> None:
    workers = [Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob")]
    constants = constants_for(workers, {"any": 2}, 4, 4, parameters=ScoringParameters(likes_weight=0))
    penalty = score(constants, [0, 1])
    assert penalty.likes > 0
    assert penalty.total == pytest.approx(penalty.workload / 2 + penalty.rest / 2)  # the other two weights are equal


# --- properties, on the example ---

@pytest.fixture(scope="module")
def example() -> tuple[ScoringConstants, tuple[int, ...]]:
    """The example's scoring constants and the schedule the search finds for it."""
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    return constants, assignment


def fill_in_order(assignment: tuple[int, ...], order: list[int]) -> list[list[int | None]]:
    """The partial assignments reached by filling the slots of `assignment` in the given order."""
    partial: list[int | None] = [None] * len(assignment)
    steps = [list(partial)]
    for slot_index in order:
        partial[slot_index] = assignment[slot_index]
        steps.append(list(partial))
    return steps


@pytest.mark.parametrize("seed", range(10))
def test_filling_slots_never_lowers_the_penalty(example: tuple[ScoringConstants, tuple[int, ...]],
                                                seed: int) -> None:
    constants, assignment = example
    order = random.Random(seed).sample(range(len(assignment)), len(assignment))
    previous = score(constants, [None] * len(assignment))
    assert previous.total == 0
    for partial in fill_in_order(assignment, order)[1:]:
        current = score(constants, partial)
        for part in ("total", "likes", "workload", "rest"):
            assert getattr(current, part) >= getattr(previous, part), part
        previous = current


def test_the_penalty_doesnt_depend_on_the_order_slots_were_filled(
        example: tuple[ScoringConstants, tuple[int, ...]]) -> None:
    constants, assignment = example
    half = len(assignment) // 2
    first_half = list(range(half))
    reached = [fill_in_order(assignment, random.Random(seed).sample(first_half, half))[-1] for seed in range(5)]
    assert all(partial == reached[0] for partial in reached)
    assert len({score(constants, partial) for partial in reached}) == 1  # exactly equal, not just close


def test_every_part_is_at_least_zero(example: tuple[ScoringConstants, tuple[int, ...]]) -> None:
    constants, assignment = example
    penalty = score(constants, assignment)
    assert all(part >= 0 for part in (penalty.total, penalty.likes, penalty.workload, penalty.rest))


@pytest.mark.parametrize("period_hours", [16, 32, 64])
def test_one_event_costs_the_same_at_any_length(period_hours: int) -> None:
    # the flat penalty (ADR 0032): two workers sharing a 4-hour post evenly, then one of them taking one more shift
    # and the other one fewer; and a two-slot shift with a disliked partner instead of a neutral one
    constants = constants_for([Worker("Anne"), Worker("Bob")], {"any": 1}, 4, period_hours)
    shifts = period_hours // 4
    even = [index % 2 for index in range(shifts)]
    uneven = list(even)
    uneven[1] = 0  # Bob's first shift goes to Anne
    # a two-shift gap: 2 workload units, whatever the length
    assert workload_penalty(constants, uneven) - workload_penalty(constants, even) == pytest.approx(2)
    pair = constants_for([Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob")], {"any": 2}, 4, period_hours)
    filled = [0, 1] + [None] * (2 * shifts - 2)
    assert likes_penalty(pair, filled) == pytest.approx(1 + ALPHA)  # Anne's dislike and Bob's neutral view


def test_scoring_is_deterministic(example: tuple[ScoringConstants, tuple[int, ...]]) -> None:
    constants, assignment = example
    assert score(constants, assignment) == score(constants, list(assignment))


def test_weights_change_only_the_total(example: tuple[ScoringConstants, tuple[int, ...]]) -> None:
    constants, assignment = example
    reweighted = dataclasses.replace(constants, parameters=ScoringParameters(1, 1, 1))
    default, equal = score(constants, assignment), score(reweighted, assignment)
    assert (default.likes, default.workload, default.rest) == (equal.likes, equal.workload, equal.rest)
    assert equal.total == pytest.approx((equal.likes + equal.workload + equal.rest) / 3)


def test_workload_penalty_ranks_schedules_by_the_spread_of_workloads() -> None:
    # With p = 2, the workload penalty is the availability-weighted variance of workloads plus a constant, so over all
    # complete schedules it must rank them exactly as that variance does. Every legal schedule of a small input:
    away = Worker("Cy", unavailable=(DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 4)),))
    workers = [Worker("Anne"), Worker("Bob"), away]
    start = dt.datetime(2025, 1, 1)
    settings = Settings(DateTimeRange(start, start + dt.timedelta(hours=12)), dt.timedelta(hours=2))
    schedule_input = ScheduleInput(settings, tuple(workers), (Post("post", ShiftRules(dt.timedelta(hours=2),
                                                                                   (("any", 1),))),))
    problem = build_problem(schedule_input)
    constants = build_constants(settings, problem.workers, problem.shifts, problem.slots, problem.domains)
    schedules = [assignment for assignment in product(range(3), repeat=len(problem.slots))
                 if not hard_constraint_violations(schedule_input, problem.slots, assignment)]
    assert len(schedules) > 10

    def weighted_variance(assignment: tuple[int, ...]) -> float:
        availability = [worker.availability for worker in constants.workers]
        assigned = [sum(constants.slot_load[slot] for slot, worker in enumerate(assignment) if worker == index)
                    for index in range(3)]
        mean = sum(assigned) / sum(availability)
        return sum(av * (hours / av - mean) ** 2 for av, hours in zip(availability, assigned))

    by_spread = sorted(schedules, key=weighted_variance)
    penalties = [workload_penalty(constants, assignment) for assignment in by_spread]
    assert all(earlier <= later + 1e-12 for earlier, later in zip(penalties, penalties[1:]))


def test_the_water_level_respects_each_workers_cap() -> None:
    # two workers with 1 hour available each, 4 hours to spread: evenly, 2 each; if one can take only 1, the other 3
    assert _water_level([(0.0, 1.0, 10.0), (0.0, 1.0, 10.0)], 4.0) == pytest.approx(2.0)
    assert _water_level([(0.0, 1.0, 1.0), (0.0, 1.0, 10.0)], 4.0) == pytest.approx(3.0)
    # a worker already above the level keeps their own
    assert _water_level([(0.0, 1.0, 10.0), (5.0, 1.0, 10.0)], 2.0) == pytest.approx(2.0)
    assert _water_level([], 3.0) == 0.0


# --- the shift share (ADR 0026) ---

def shifts_input(shift_share: float) -> tuple[ScoringConstants, list]:
    """A 4-hour period with a desk of 2-hour shifts and a gate of 1-hour shifts, for Anne, Bob and Cy."""
    start = dt.datetime(2025, 1, 1)
    period = DateTimeRange(start, start + dt.timedelta(hours=4))
    posts = (Post("desk", ShiftRules(dt.timedelta(hours=2), (("any", 1),))),
             Post("gate", ShiftRules(dt.timedelta(hours=1), (("any", 1),))))
    workers = (Worker("Anne"), Worker("Bob"), Worker("Cy"))
    settings = Settings(period, dt.timedelta(0), ScoringParameters(shift_share=shift_share))
    problem = build_problem(ScheduleInput(settings, workers, posts))
    return build_constants(settings, problem.workers, problem.shifts, problem.slots, problem.domains), problem.slots


def schedule(slots: list, plan: dict[tuple[str, int], int]) -> list[int]:
    """An assignment from (post, start hour) -> worker."""
    return [plan[(slot.post.name, slot.time.start.hour)] for slot in slots]


# Anne works both desk shifts (4 h, 2 shifts); Bob and Cy two gate shifts each (2 h, 2 shifts)
EVEN_SHIFTS = {("desk", 0): 0, ("desk", 2): 0, ("gate", 0): 1, ("gate", 1): 1, ("gate", 2): 2, ("gate", 3): 2}
# the same hours, but Anne works all four gate shifts (4 h, 4 shifts), Bob and Cy a desk shift each (2 h, 1 shift)
UNEVEN_SHIFTS = {("desk", 0): 1, ("desk", 2): 2, ("gate", 0): 0, ("gate", 1): 0, ("gate", 2): 0, ("gate", 3): 0}
# the same shift counts as EVEN_SHIFTS, but hours spread more evenly (3, 3 and 2)
EVEN_HOURS = {("desk", 0): 0, ("gate", 2): 0, ("desk", 2): 1, ("gate", 0): 1, ("gate", 1): 2, ("gate", 3): 2}


def test_with_no_shift_share_only_hours_count() -> None:
    constants, slots = shifts_input(0)
    assert constants.slot_load == constants.slot_hours
    assert workload_penalty(constants, schedule(slots, EVEN_SHIFTS)) == pytest.approx(
        workload_penalty(constants, schedule(slots, UNEVEN_SHIFTS)))
    assert workload_penalty(constants, schedule(slots, EVEN_HOURS)) < workload_penalty(constants,
                                                                                       schedule(slots, EVEN_SHIFTS))


def test_with_a_full_shift_share_only_shifts_count() -> None:
    constants, slots = shifts_input(1)
    assert len(set(constants.slot_load)) == 1
    assert workload_penalty(constants, schedule(slots, EVEN_HOURS)) == pytest.approx(
        workload_penalty(constants, schedule(slots, EVEN_SHIFTS)))


def test_a_shift_share_makes_many_short_shifts_count_against_few_long_ones() -> None:
    constants, slots = shifts_input(0.5)
    assert workload_penalty(constants, schedule(slots, UNEVEN_SHIFTS)) > workload_penalty(
        constants, schedule(slots, EVEN_SHIFTS))
