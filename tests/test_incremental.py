"""Tests for tinyscheg.scoring.incremental, against the from-scratch scoring as the oracle (ADR 0027)."""
import dataclasses
import random
from itertools import product

import pytest

from schedule_checker import hard_constraint_violations
from test_search import constants_of, small_inputs
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import choose_slot, find_best_schedule
from tinyscheg.csp.state import SearchState
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.scoring.incremental import IncrementalScore
from tinyscheg.scoring.penalty import lower_bound, score

STEPS = 200             # random assignments and backtracks per input
UNDO_CHANCE = 0.35      # the chance that a step backtracks rather than assigns
TOLERANCE = 1e-9        # rounding differences allowed between the incremental and from-scratch values
LOOKAHEAD_PARTIALS = 20  # partial schedules checked per small input in the rest look-ahead test


def assert_matches(incremental: IncrementalScore, state: SearchState) -> None:
    """The incremental totals and bound agree with the from-scratch ones on the current state."""
    constants = incremental.constants
    assert incremental.total() == pytest.approx(score(constants, state.assigned).total, abs=TOLERANCE)
    assert incremental.bound() == pytest.approx(lower_bound(constants, state.assigned, state.domains), abs=TOLERANCE)
    # the bound without its whole-slot part, which the search checks first, is never above the full one
    assert incremental.bound_without_whole_slots() <= incremental.bound()


@pytest.mark.parametrize("role_aware_bound", ["on", "off"])
@pytest.mark.parametrize("schedule_input", small_inputs())
def test_incremental_scoring_matches_scoring_from_scratch(schedule_input: ScheduleInput,
                                                          role_aware_bound: str) -> None:
    # with either kind of whole-slot sets (ADR 0047)
    schedule_input = dataclasses.replace(schedule_input, settings=dataclasses.replace(
        schedule_input.settings, role_aware_bound=role_aware_bound))
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


def test_an_incremental_score_can_start_from_a_partly_filled_schedule() -> None:
    # as with a history (ADR 0031): the totals of what's filled are computed from scratch, then kept up to date
    schedule_input = small_inputs()[0]
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    state = SearchState(problem)
    for _ in range(3):
        slot = choose_slot(state)
        assert slot is not None
        assert state.assign(slot, state.domains[slot][0]).emptied is None
    incremental = IncrementalScore(constants, state.assigned, state.domains)
    assert_matches(incremental, state)
    slot = choose_slot(state)
    assert slot is not None
    changes = state.assign(slot, state.domains[slot][0])
    assert changes.emptied is None
    incremental.assign(slot, state.assigned[slot], changes.saved_domains)
    assert_matches(incremental, state)
    state.undo(changes)
    incremental.undo()
    assert_matches(incremental, state)


def test_the_rest_lookahead_is_never_above_what_a_completion_adds() -> None:
    # ADR 0045: on partial schedules of the small inputs (some slots of a legal schedule left unfilled, the domains as
    # forward checking leaves them), the rest so far plus the look-ahead is never above the rest of any completion;
    # and it means something: it's above 0 on some of them
    rng = random.Random(0)
    positive = 0
    for schedule_input in small_inputs():
        problem, constants = build_problem(schedule_input), constants_of(schedule_input)
        legal = [assignment for assignment in product(*problem.domains)
                 if not hard_constraint_violations(schedule_input, problem.slots, assignment)]
        for _ in range(LOOKAHEAD_PARTIALS if legal else 0):
            source = rng.choice(legal)
            partial = [worker if rng.random() < 0.5 else None for worker in source]
            domains = [tuple(worker for worker in domain
                             if all(partial[neighbour] != worker for neighbour in problem.neighbours[slot]))
                       if partial[slot] is None else (partial[slot],)
                       for slot, domain in enumerate(problem.domains)]
            completions = [assignment for assignment in legal
                           if all(filled is None or filled == worker for filled, worker in zip(partial, assignment))]
            least_rest = min(score(constants, assignment).rest for assignment in completions)
            incremental = IncrementalScore(constants, partial, domains)
            lookahead = incremental.rest_lookahead(problem.neighbours)
            assert incremental.rest + lookahead <= least_rest + TOLERANCE
            positive += lookahead > 0
    assert positive > 0


@pytest.mark.parametrize("schedule_input", small_inputs())
def test_the_search_finds_the_same_schedule_with_and_without_the_rest_lookahead(
        schedule_input: ScheduleInput, monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR 0045: a valid bound only cuts branches that can't beat the pocket, so the result is exactly the same
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    with_it = find_best_schedule(problem, constants)
    monkeypatch.setattr(IncrementalScore, "rest_lookahead", lambda self, neighbours: 0.0)
    without_it = find_best_schedule(problem, constants)
    assert (with_it.assignment, with_it.penalty) == (without_it.assignment, without_it.penalty)
    assert with_it.nodes <= without_it.nodes
