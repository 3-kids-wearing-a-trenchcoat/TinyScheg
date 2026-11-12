"""Tests for tinyscheg.csp.problem."""
import datetime as dt
import itertools
import pathlib

from tinyscheg.csp.problem import (build_problem, difference_constraints, initial_domain, interchangeable_slots,
                                   must_differ,
                                   unfillable_slots)
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, Settings
from tinyscheg.model.shift import Slot
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"
POST = Post("desk", ShiftRules(dt.timedelta(hours=1), (("any", 1),)))


def at(hour: int) -> dt.datetime:
    """A datetime on 2025-01-01 at hour:00 (hours past 23 roll over into the next days)."""
    return dt.datetime(2025, 1, 1) + dt.timedelta(hours=hour)


def slot(index: int, start: int, end: int, role: str = "any", shift_index: int | None = None) -> Slot:
    """A slot from start to end o'clock (in hours from 2025-01-01 00:00)."""
    return Slot(index, index if shift_index is None else shift_index, POST, DateTimeRange(at(start), at(end)), role)


def hours(value: float) -> dt.timedelta:
    """A timedelta of the given number of hours."""
    return dt.timedelta(hours=value)


# --- domains ---

def test_domain_filters_by_role() -> None:
    workers = [Worker("Anne"), Worker("Bob", roles=frozenset({"medic"})), Worker("Cy", roles=frozenset({"medic"}))]
    assert initial_domain(slot(0, 8, 12, "medic"), workers) == (1, 2)
    assert initial_domain(slot(0, 8, 12, "any"), workers) == (0, 1, 2)


def test_domain_filters_by_availability() -> None:
    def unavailable(start: int, end: int) -> Worker:
        return Worker(f"away {start}-{end}", unavailable=(DateTimeRange(at(start), at(end)),))

    workers = [unavailable(11, 13),   # partly overlaps the slot: excluded
               unavailable(6, 8),     # ends as the slot starts: available
               unavailable(12, 14),   # starts as the slot ends: available
               unavailable(9, 10)]    # inside the slot: excluded
    assert initial_domain(slot(0, 8, 12), workers) == (1, 2)


# --- difference constraints ---

def test_overlapping_slots_are_constrained() -> None:
    assert difference_constraints([slot(0, 8, 12), slot(1, 10, 14)], hours(0)) == ((1,), (0,))


def test_rest_of_exactly_min_rest_is_allowed() -> None:
    first = slot(0, 8, 12)
    assert must_differ(first, slot(1, 17, 20), hours(5.5))       # 5 hours apart, less than 5.5
    assert not must_differ(first, slot(1, 17, 20), hours(5))     # exactly 5 hours apart


def test_back_to_back_slots_with_no_minimum_rest() -> None:
    assert difference_constraints([slot(0, 8, 12), slot(1, 12, 16)], hours(0)) == ((), ())
    assert difference_constraints([slot(0, 8, 12), slot(1, 12, 16)], hours(1)) == ((1,), (0,))


def test_slots_of_the_same_shift_are_constrained() -> None:
    slots = [slot(0, 8, 12, shift_index=0), slot(1, 8, 12, shift_index=0)]
    assert difference_constraints(slots, hours(0)) == ((1,), (0,))


def test_long_slot_constrains_a_later_short_one_inside_it() -> None:
    slots = [slot(0, 0, 24), slot(1, 2, 3), slot(2, 20, 21), slot(3, 29, 30)]  # slot 3: 5 hours after slot 0
    assert difference_constraints(slots, hours(6)) == ((1, 2, 3), (0,), (0,), (0,))


def test_scan_does_not_stop_too_early() -> None:
    # slot 1 is far from slot 0's end but slot 2, starting later, still overlaps slot 0's rest period
    slots = [slot(0, 0, 10), slot(1, 1, 2), slot(2, 12, 13), slot(3, 16, 17)]
    neighbours = difference_constraints(slots, hours(5))
    assert neighbours[0] == (1, 2)


def test_constraints_match_brute_force_on_the_example() -> None:
    problem = build_problem(read_input(EXAMPLE_INPUT))
    for first, second in itertools.permutations(problem.slots, 2):
        expected = must_differ(first, second, problem.min_rest)
        assert (second.index in problem.neighbours[first.index]) is expected, (first, second)
    for index, neighbours in enumerate(problem.neighbours):
        assert index not in neighbours and list(neighbours) == sorted(neighbours)


# --- the problem as a whole ---

def test_build_problem_from_the_example() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assert problem.workers == schedule_input.workers
    assert problem.min_rest == dt.timedelta(hours=6)
    assert len(problem.slots) == len(problem.domains) == len(problem.neighbours) == 17
    assert [slot.index for slot in problem.slots] == list(range(17))
    assert unfillable_slots(problem) == ()
    # the desk needs a supervisor: Jack, Jill, Gilgamesh or Shamhat, when available
    desk_domains = {problem.domains[slot.index] for slot in problem.slots if slot.post.name == "desk"}
    assert desk_domains <= {(0, 1, 4, 7), (1, 4, 7), (0, 4, 7)}


def test_unfillable_slots() -> None:
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("medic", 1), ("any", 1))))
    schedule_input = ScheduleInput(Settings(DateTimeRange(at(0), at(8))), (Worker("Anne"),), (post,))
    unfillable = unfillable_slots(build_problem(schedule_input))
    assert [(slot.role, slot.time.start.hour) for slot in unfillable] == [("medic", 0), ("medic", 4)]


def test_build_problem_is_deterministic() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    assert build_problem(schedule_input) == build_problem(schedule_input)


def test_interchangeable_slots_share_a_shift_and_a_role() -> None:
    # one 4-hour shift needing a medic and 2 of anyone, then another
    period = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 8))
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("medic", 1), ("any", 2))))
    problem = build_problem(ScheduleInput(Settings(period), (Worker("Anne"),), (post,)))
    assert [slot.role for slot in problem.slots] == ["medic", "any", "any"] * 2
    assert problem.interchangeable == ((), (2,), (1,), (), (5,), (4,))
    assert interchangeable_slots(problem.slots) == problem.interchangeable
