"""Tests for tinyscheg.csp.search."""
import dataclasses
import datetime as dt
import pathlib
import random
import time

import pytest

from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import _Search, choose_slot, find_first_schedule
from tinyscheg.csp.state import SearchState
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"
SLOW_CASE_SECONDS = 5  # filling slots in stable order took minutes on this case; MRV takes a fraction of a second


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
    # the example's first six workers plus one, with five hours' rest: no legal schedule, which filling slots in
    # stable order took minutes to establish
    schedule_input = read_input(EXAMPLE_INPUT)
    hard = dataclasses.replace(schedule_input, workers=schedule_input.workers[:6] + (Worker("Ninsun"),),
                               settings=dataclasses.replace(schedule_input.settings, min_rest=dt.timedelta(hours=5)))
    started = time.perf_counter()
    result = find_first_schedule(build_problem(hard))
    assert time.perf_counter() - started < SLOW_CASE_SECONDS
    assert result.assignment is None
