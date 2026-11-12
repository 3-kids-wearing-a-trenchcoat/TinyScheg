"""Tests for tinyscheg.csp.state."""
import datetime as dt

import pytest

from tinyscheg.csp.problem import Problem
from tinyscheg.csp.state import SearchState
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.shift import Slot
from tinyscheg.model.worker import Worker
from tinyscheg.timing.datetime_range import DateTimeRange

POST = Post("desk", ShiftRules(dt.timedelta(hours=1), (("any", 1),)))


def problem(domains: list[tuple[int, ...]], neighbours: list[tuple[int, ...]]) -> Problem:
    """A Problem with the given domains and constraints; slot times don't matter to the state."""
    time = DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1, 1))
    slots = tuple(Slot(index, index, POST, time, "any") for index in range(len(domains)))
    workers = tuple(Worker(f"w{index}") for index in range(3))
    return Problem(workers, (), slots, tuple(domains), tuple(neighbours), dt.timedelta(0))


# slot 0 is constrained with 1 and 2; 1 and 2 aren't constrained with each other
TRIANGLE = problem([(0, 1, 2), (0, 1), (0, 2)], [(1, 2), (0,), (0,)])


def test_assign_removes_the_worker_from_neighbours() -> None:
    state = SearchState(TRIANGLE)
    changes = state.assign(0, 0)
    assert state.assigned == [0, None, None]
    assert state.domains == [(0, 1, 2), (1,), (2,)]
    assert changes.saved_domains == ((1, (0, 1)), (2, (0, 2)))
    assert changes.emptied is None


def test_assigned_neighbours_are_left_alone() -> None:
    state = SearchState(TRIANGLE)
    state.assign(1, 1)
    changes = state.assign(0, 0)
    assert changes.saved_domains == ((2, (0, 2)),)
    assert state.domains[1] == (0, 1)  # assigned already, so not forward checked


def test_emptied_domain_is_reported() -> None:
    state = SearchState(problem([(0, 1), (0,), (0,)], [(1, 2), (0,), (0,)]))
    changes = state.assign(0, 0)
    assert changes.emptied == 1
    assert changes.saved_domains == ((1, (0,)),)  # checking stopped at the first empty domain
    assert state.domains[2] == (0,)


def test_undo_restores_the_state_exactly() -> None:
    state = SearchState(TRIANGLE)
    first = state.assign(0, 1)
    second = state.assign(1, 0)
    state.undo(second)
    assert state.assigned == [1, None, None] and state.domains == [(0, 1, 2), (0,), (0, 2)]
    state.undo(first)
    assert state.assigned == [None, None, None] and state.domains == list(TRIANGLE.domains)


@pytest.mark.parametrize("slot_index, worker", [(0, 5), (1, 2)])
def test_assigning_a_worker_outside_the_domain_is_an_error(slot_index: int, worker: int) -> None:
    with pytest.raises(ValueError):
        SearchState(TRIANGLE).assign(slot_index, worker)


def test_assigning_an_assigned_slot_is_an_error() -> None:
    state = SearchState(TRIANGLE)
    state.assign(0, 0)
    with pytest.raises(ValueError):
        state.assign(0, 1)


def test_interchangeable_slots_are_kept_in_ascending_worker_order() -> None:
    # slots 0, 1 and 2 are one shift's interchangeable slots (and so constrained with each other)
    base = problem([(0, 1, 2)] * 3, [(1, 2), (0, 2), (0, 1)])
    ordered = Problem(base.workers, (), base.slots, base.domains, base.neighbours, base.min_rest,
                      interchangeable=((1, 2), (0, 2), (0, 1)))
    state = SearchState(ordered)
    changes = state.assign(1, 1)
    assert state.domains == [(0,), (0, 1, 2), (2,)]  # earlier slots get the workers before, later ones those after
    state.undo(changes)
    assert state.domains == [(0, 1, 2)] * 3
    assert state.assign(1, 2).emptied == 2  # nobody comes after the last worker
