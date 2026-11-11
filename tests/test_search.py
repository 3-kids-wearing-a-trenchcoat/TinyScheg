"""Tests for tinyscheg.csp.search."""
import dataclasses
import datetime as dt
import pathlib

from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import _Search, find_first_schedule
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"


def assert_legal(schedule_input: ScheduleInput) -> tuple[int, ...]:
    """Search the input, check the schedule found with the independent checker, and return it."""
    problem = build_problem(schedule_input)
    result = find_first_schedule(problem)
    assert result.assignment is not None and result.stuck_slot is None
    assert hard_constraint_violations(schedule_input, problem.slots, result.assignment) == []
    return result.assignment


def example_with_min_rest(hours: int) -> ScheduleInput:
    """exampleInput.yml with a different minimum rest."""
    schedule_input = read_input(EXAMPLE_INPUT)
    settings = dataclasses.replace(schedule_input.settings, min_rest=dt.timedelta(hours=hours))
    return dataclasses.replace(schedule_input, settings=settings)


def test_example_input_is_infeasible() -> None:
    # The night front gate needs 2 workers per 3-hour shift. With 5 hours' rest, the shifts 00-03, 03-06 and 06-07
    # need all 6 workers, leaving nobody rested for the 07-10 shift.
    problem = build_problem(read_input(EXAMPLE_INPUT))
    result = find_first_schedule(problem)
    assert result.assignment is None
    assert result.deepest == 5
    assert result.stuck_slot is not None and result.stuck_slot.time.start == dt.datetime(2025, 1, 1, 6)


def test_example_with_less_rest_has_a_legal_schedule() -> None:
    assert_legal(example_with_min_rest(3))


def test_search_is_deterministic() -> None:
    schedule_input = example_with_min_rest(3)
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
    assert result.assignment is None and result.deepest == 1 and result.stuck_slot == problem.slots[1]


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
