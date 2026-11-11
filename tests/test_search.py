"""Tests for tinyscheg.csp.search."""
import dataclasses
import datetime as dt
import math
import pathlib
import random
import time
from itertools import product

import pytest

from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import _Search, choose_slot, find_best_schedule, find_first_schedule
from tinyscheg.csp.state import SearchState
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.constants import ScoringConstants, build_constants
from tinyscheg.scoring.penalty import lower_bound, score
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"
BRUTE_FORCE_LIMIT = 20000  # the most schedules (combinations of domains) a brute-force test input may have
BRUTE_FORCE_MINIMUM = 50   # the fewest, so that every input takes some searching
BOUND_PARTIALS = 20         # partial schedules checked per small input in the lower-bound test
BRUTE_FORCE_INPUTS = 25    # how many random small inputs are compared with brute force
LOCAL_CHECK_HOURS = (12, 14)  # lengths of the example that branch and bound finishes in well under a second
SLOW_CASE_SECONDS = 5      # filling slots in stable order took minutes on this case; MRV takes a fraction of a second


def assert_legal(schedule_input: ScheduleInput) -> tuple[int, ...]:
    """Search the input, check the schedule found with the independent checker, and return it."""
    problem = build_problem(schedule_input)
    result = find_first_schedule(problem)
    assert result.assignment is not None and result.stuck_slot is None
    assert hard_constraint_violations(schedule_input, problem.slots, result.assignment) == []
    return result.assignment


def test_example_input_has_a_legal_schedule() -> None:
    assert_legal(read_input(EXAMPLE_INPUT))


def test_search_is_deterministic() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    assert assert_legal(schedule_input) == assert_legal(schedule_input)


def test_workers_are_tried_in_input_order() -> None:
    period = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 4))
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 2),)))
    schedule_input = ScheduleInput(Settings(period), (Worker("Anne"), Worker("Bob"), Worker("Cy")), (post,))
    assert assert_legal(schedule_input) == (0, 1)


def test_infeasible_input_reports_where_it_got_stuck() -> None:
    # two 2-worker shifts back to back, with a rest of an hour: all four slots need different workers
    period = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 8))
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 2),)))
    workers = tuple(Worker(name) for name in ("Anne", "Bob", "Cy"))
    schedule_input = ScheduleInput(Settings(period, dt.timedelta(hours=1)), workers, (post,))
    problem = build_problem(schedule_input)
    result = find_first_schedule(problem)
    assert result.assignment is None
    # with 3 workers, filling the first shift and one slot of the second leaves nobody for the last slot, which
    # forward checking sees as soon as the second shift's first slot is filled: the search fills 2 slots at most
    assert result.deepest == 2
    assert result.stuck_slot == problem.slots[2]

    feasible = ScheduleInput(schedule_input.settings, workers + (Worker("Dan"),), (post,))
    assert assert_legal(feasible) == (0, 1, 2, 3)


def test_unfillable_slot_is_where_the_search_gets_stuck() -> None:
    period = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 4))
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1), ("medic", 1))))
    problem = build_problem(ScheduleInput(Settings(period), (Worker("Anne"), Worker("Bob")), (post,)))
    result = find_first_schedule(problem)
    # the medic slot has the smallest (empty) domain, so it's chosen first, before anything is filled
    assert result.assignment is None and result.deepest == 0 and result.stuck_slot == problem.slots[1]


def test_failed_search_undoes_every_change() -> None:
    period = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 8))
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 2),)))
    workers = tuple(Worker(name) for name in ("Anne", "Bob", "Cy"))
    problem = build_problem(ScheduleInput(Settings(period, dt.timedelta(hours=1)), workers, (post,)))
    run = _Search(problem)
    assert run.search() is False
    assert run.state.domains == list(problem.domains)
    assert run.state.assigned == [None] * len(problem.slots)
    assert run.filled == 0


# --- choosing the next slot ---

def one_post_state(workers: tuple[Worker, ...], roles: dict[str, int], length: int, period_hours: int,
                   min_rest: int = 0) -> SearchState:
    """A fresh search state for a one-post input: shifts of `length` hours over the first period_hours of 2025."""
    start = dt.datetime(2025, 1, 1)
    period = DateTimeRange(start, start + dt.timedelta(hours=period_hours))
    post = Post("gate", ShiftRules(dt.timedelta(hours=length), tuple(roles.items())))
    return SearchState(build_problem(ScheduleInput(Settings(period, dt.timedelta(hours=min_rest)), workers, (post,))))


def test_the_smallest_domain_is_chosen_first() -> None:
    state = one_post_state((Worker("Anne", roles=frozenset({"medic"})), Worker("Bob"), Worker("Cy")),
                           {"any": 1, "medic": 1}, 4, 4)
    chosen = choose_slot(state)
    assert chosen is not None and state.domains[chosen] == (0,)


def test_degree_breaks_ties_in_domain_size() -> None:
    # three single-slot shifts in a row, an hour's rest: the middle one is constrained with both others
    state = one_post_state((Worker("Anne"), Worker("Bob"), Worker("Cy")), {"any": 1}, 4, 12, min_rest=1)
    assert choose_slot(state) == 1


def test_the_lowest_index_breaks_full_ties() -> None:
    state = one_post_state((Worker("Anne"), Worker("Bob"), Worker("Cy")), {"any": 2}, 4, 4)
    assert choose_slot(state) == 0


def test_assigned_slots_are_skipped() -> None:
    state = one_post_state((Worker("Anne"), Worker("Bob"), Worker("Cy")), {"any": 1}, 4, 12, min_rest=1)
    state.assign(1, 0)
    assert choose_slot(state) == 0  # both ends now have two workers left and no unassigned neighbours
    state.assign(0, 1)
    assert choose_slot(state) == 2
    state.assign(2, 1)
    assert choose_slot(state) is None


# --- the search as a whole ---

@pytest.mark.parametrize("seed", range(5))
def test_legal_schedules_for_shuffled_worker_orders(seed: int) -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    workers = list(schedule_input.workers)
    random.Random(seed).shuffle(workers)
    shuffled = dataclasses.replace(schedule_input, workers=tuple(workers))
    assert assert_legal(shuffled) == assert_legal(shuffled)


def test_infeasibility_is_found_quickly_on_a_hard_input() -> None:
    # the example's first six workers plus one, over three days with five hours' rest: no legal schedule, which
    # filling slots in stable order took minutes to establish
    schedule_input = read_input(EXAMPLE_INPUT)
    three_days = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 4))
    hard = dataclasses.replace(schedule_input, workers=schedule_input.workers[:6] + (Worker("Ninsun"),),
                               settings=dataclasses.replace(schedule_input.settings, period=three_days,
                                                            min_rest=dt.timedelta(hours=5)))
    started = time.perf_counter()
    result = find_first_schedule(build_problem(hard))
    assert time.perf_counter() - started < SLOW_CASE_SECONDS
    assert result.assignment is None


# --- branch and bound ---

def random_small_input(seed: int) -> ScheduleInput:
    """A random input small enough to try every schedule: 3 or 4 workers, a few short shifts on one or two posts."""
    rng = random.Random(seed)
    names = ["Anne", "Bob", "Cy", "Dan"][:rng.randint(3, 4)]
    period = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, rng.choice([8, 12])))
    workers = []
    for name in names:
        others = [other for other in names if other != name]
        liked = frozenset(other for other in others if rng.random() < 0.3)
        disliked = frozenset(other for other in others if other not in liked and rng.random() < 0.3)
        unavailable = ()
        if rng.random() < 0.3:
            start = period.start + dt.timedelta(hours=rng.randrange(0, 8, 2))
            unavailable = (DateTimeRange(start, start + dt.timedelta(hours=rng.choice([2, 4]))),)
        roles = frozenset({"medic"}) if rng.random() < 0.5 else frozenset()
        workers.append(Worker(name, roles, unavailable, liked, disliked))
    posts = [Post("gate", ShiftRules(dt.timedelta(hours=rng.choice([2, 4])), (("any", rng.randint(1, 2)),)))]
    if rng.random() < 0.5:
        posts.append(Post("aid", ShiftRules(dt.timedelta(hours=4), (("medic", 1),))))
    settings = Settings(period, dt.timedelta(hours=rng.choice([0, 1, 2, 4])))
    return ScheduleInput(settings, tuple(workers), tuple(posts))


def small_inputs() -> list[ScheduleInput]:
    """The first BRUTE_FORCE_INPUTS random small inputs with between BRUTE_FORCE_MINIMUM and BRUTE_FORCE_LIMIT
    schedules to try."""
    inputs = []
    seed = 0
    while len(inputs) < BRUTE_FORCE_INPUTS:
        schedule_input = random_small_input(seed)
        if BRUTE_FORCE_MINIMUM <= math.prod(len(domain) for domain in build_problem(schedule_input).domains) \
                <= BRUTE_FORCE_LIMIT:
            inputs.append(schedule_input)
        seed += 1
    return inputs


def constants_of(schedule_input: ScheduleInput) -> ScoringConstants:
    """The scoring constants of an input."""
    problem = build_problem(schedule_input)
    return build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots, problem.domains)


@pytest.mark.parametrize("schedule_input", small_inputs())
def test_branch_and_bound_finds_the_best_schedule(schedule_input: ScheduleInput) -> None:
    problem = build_problem(schedule_input)
    constants = constants_of(schedule_input)
    legal = [assignment for assignment in product(*problem.domains)
             if not hard_constraint_violations(schedule_input, problem.slots, assignment)]
    result = find_best_schedule(problem, constants)
    if not legal:
        assert result.assignment is None and result.penalty is None
        return
    penalties = {assignment: score(constants, assignment).total for assignment in legal}
    lowest = min(penalties.values())
    assert result.assignment is not None and result.penalty is not None
    assert hard_constraint_violations(schedule_input, problem.slots, result.assignment) == []
    assert result.penalty.total == lowest  # exactly: penalties are computed from scratch, the same way
    assert result.penalty == score(constants, result.assignment)
    best = [assignment for assignment, penalty in penalties.items() if penalty == lowest]
    if len(best) == 1:
        assert result.assignment == best[0]


def test_the_small_inputs_cover_feasible_and_infeasible_cases() -> None:
    found = [find_best_schedule(build_problem(schedule_input), constants_of(schedule_input)).assignment
             for schedule_input in small_inputs()]
    assert any(assignment is None for assignment in found) and any(assignment is not None for assignment in found)


def test_pruning_loses_nothing() -> None:
    fewer = 0
    for schedule_input in small_inputs():
        problem, constants = build_problem(schedule_input), constants_of(schedule_input)
        pruned, full = find_best_schedule(problem, constants), find_best_schedule(problem, constants, prune=False)
        assert (pruned.assignment, pruned.penalty) == (full.assignment, full.penalty)
        assert pruned.nodes <= full.nodes and full.pruned == 0
        fewer += pruned.nodes < full.nodes
    assert fewer > 0


def test_branch_and_bound_is_deterministic() -> None:
    schedule_input = small_inputs()[0]
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    assert find_best_schedule(problem, constants) == find_best_schedule(problem, constants)


def test_branch_and_bound_reports_where_an_infeasible_input_got_stuck() -> None:
    period = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 8))
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 2),)))
    workers = tuple(Worker(name) for name in ("Anne", "Bob", "Cy"))
    schedule_input = ScheduleInput(Settings(period, dt.timedelta(hours=1)), workers, (post,))
    problem = build_problem(schedule_input)
    first, best = find_first_schedule(problem), find_best_schedule(problem, constants_of(schedule_input))
    assert best.assignment is None and best.penalty is None
    assert (best.deepest, best.stuck_slot) == (first.deepest, first.stuck_slot)


def single_changes(assignment: tuple[int, ...], worker_count: int) -> list[tuple[int, ...]]:
    """Every schedule one move (a slot to another worker) or one swap (two slots exchanging workers) away."""
    changed = []
    for slot in range(len(assignment)):
        for worker in range(worker_count):
            if worker != assignment[slot]:
                changed.append(assignment[:slot] + (worker,) + assignment[slot + 1:])
    for first in range(len(assignment)):
        for second in range(first + 1, len(assignment)):
            if assignment[first] != assignment[second]:
                swapped = list(assignment)
                swapped[first], swapped[second] = swapped[second], swapped[first]
                changed.append(tuple(swapped))
    return changed


@pytest.mark.parametrize("hours", LOCAL_CHECK_HOURS)
def test_no_single_change_beats_the_best_schedule(hours: int) -> None:
    # branch and bound's schedule must be at least as good as every legal schedule one move or swap away from it
    schedule_input = read_input(EXAMPLE_INPUT)
    start = schedule_input.settings.period.start
    shorter = dataclasses.replace(schedule_input, settings=dataclasses.replace(
        schedule_input.settings, period=DateTimeRange(start, start + dt.timedelta(hours=hours))))
    problem, constants = build_problem(shorter), constants_of(shorter)
    result = find_best_schedule(problem, constants)
    assert result.assignment is not None and result.penalty is not None
    neighbours = [assignment for assignment in single_changes(result.assignment, len(shorter.workers))
                  if not hard_constraint_violations(shorter, problem.slots, assignment)]
    assert neighbours  # the check means something only if there are legal alternatives
    assert all(score(constants, assignment).total >= result.penalty.total for assignment in neighbours)


@pytest.mark.parametrize("schedule_input", small_inputs())
def test_the_lower_bound_is_never_above_a_completion_nor_below_the_partial(schedule_input: ScheduleInput) -> None:
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    legal = [assignment for assignment in product(*problem.domains)
             if not hard_constraint_violations(schedule_input, problem.slots, assignment)]
    rng = random.Random(0)
    for _ in range(BOUND_PARTIALS if legal else 0):
        # a partial schedule: some slots of a legal schedule left unfilled
        source = rng.choice(legal)
        partial = [worker if rng.random() < 0.5 else None for worker in source]
        eligible = {worker for slot, assigned in enumerate(partial) if assigned is None
                    for worker in problem.domains[slot]}
        bound = lower_bound(constants, partial, eligible)
        completions = [assignment for assignment in legal
                       if all(filled is None or filled == worker for filled, worker in zip(partial, assignment))]
        assert bound <= min(score(constants, assignment).total for assignment in completions) + 1e-12
        assert bound >= score(constants, partial).total - 1e-12
