"""Tests for tinyscheg.scoring.incremental, against the from-scratch scoring as the oracle (ADR 0027)."""
import random

import pytest

from test_search import constants_of, small_inputs
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import choose_slot
from tinyscheg.csp.state import SearchState
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.scoring.incremental import IncrementalScore
from tinyscheg.scoring.penalty import lower_bound, score

STEPS = 200             # random assignments and backtracks per input
UNDO_CHANCE = 0.35      # the chance that a step backtracks rather than assigns
TOLERANCE = 1e-9        # rounding differences allowed between the incremental and from-scratch values


def assert_matches(incremental: IncrementalScore, state: SearchState) -> None:
    """The incremental totals and bound agree with the from-scratch ones on the current state."""
    constants = incremental.constants
    assert incremental.total() == pytest.approx(score(constants, state.assigned).total, abs=TOLERANCE)
    assert incremental.bound() == pytest.approx(lower_bound(constants, state.assigned, state.domains), abs=TOLERANCE)


@pytest.mark.parametrize("schedule_input", small_inputs())
def test_incremental_scoring_matches_scoring_from_scratch(schedule_input: ScheduleInput) -> None:
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    state = SearchState(problem)
    incremental = IncrementalScore(constants, state.assigned, state.domains)
    rng = random.Random(0)
    made = []  # the search's change records, latest last
    assert_matches(incremental, state)
    for _ in range(STEPS):
        slot = choose_slot(state)
        if made and (slot is None or rng.random() < UNDO_CHANCE):
            state.undo(made.pop())
            incremental.undo()
            assert_matches(incremental, state)
            continue
        if slot is None:
            break
        for worker in state.domains[slot]:  # every candidate's cost, as the value order asks for it
            state.assigned[slot] = worker
            assert incremental.cost_if(slot, worker) == pytest.approx(score(constants, state.assigned).total,
                                                                      abs=TOLERANCE)
            state.assigned[slot] = None
        changes = state.assign(slot, rng.choice(state.domains[slot]))
        if changes.emptied is not None:
            state.undo(changes)
            continue
        incremental.assign(slot, state.assigned[slot], changes.saved_domains)
        made.append(changes)
        assert_matches(incremental, state)


def test_undo_restores_every_total_exactly() -> None:
    schedule_input = small_inputs()[0]
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    state = SearchState(problem)
    incremental = IncrementalScore(constants, state.assigned, state.domains)
    before = (incremental.total(), incremental.bound(), list(incremental.caps), list(incremental.shift_bounds))
    made = []
    while (slot := choose_slot(state)) is not None:
        changes = state.assign(slot, state.domains[slot][0])
        if changes.emptied is not None:
            state.undo(changes)
            break
        incremental.assign(slot, state.assigned[slot], changes.saved_domains)
        made.append(changes)
    assert made
    while made:
        state.undo(made.pop())
        incremental.undo()
    assert (incremental.total(), incremental.bound(), incremental.caps, incremental.shift_bounds) == before


def test_an_incremental_score_starts_from_an_empty_assignment() -> None:
    schedule_input = small_inputs()[0]
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    state = SearchState(problem)
    state.assign(0, state.domains[0][0])
    with pytest.raises(ValueError, match="empty"):
        IncrementalScore(constants, state.assigned, state.domains)
