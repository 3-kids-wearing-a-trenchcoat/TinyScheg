"""Backtracking search with forward checking, stopping at the first legal schedule."""
from __future__ import annotations

from dataclasses import dataclass

from tinyscheg.csp.problem import Problem
from tinyscheg.csp.state import SearchState
from tinyscheg.model.shift import Slot


@dataclass(frozen=True, slots=True)
class SearchResult:
    """
    The outcome of a search.
    assignment holds a worker index per slot, or is None if no legal schedule exists. deepest is the most slots the
    search had filled at once, and stuck_slot the slot it had to fill next at that point (None if it found a
    schedule), for reporting where an infeasible input got stuck (ADR 0020).
    """
    assignment: tuple[int, ...] | None
    deepest: int
    stuck_slot: Slot | None


def choose_slot(state: SearchState) -> int | None:
    """
    Choose the next slot to fill (ADR 0003): the unassigned slot with the fewest workers left in its domain (MRV);
    among those, the one constrained with the most other unassigned slots (degree); among those, the lowest index
    :param state: SearchState, the current domains and assignments
    :return: the index of the slot to fill next, or None if every slot is assigned
    """
    unassigned = [index for index, worker in enumerate(state.assigned) if worker is None]
    if not unassigned:
        return None
    smallest = min(len(state.domains[index]) for index in unassigned)
    tied = [index for index in unassigned if len(state.domains[index]) == smallest]  # ascending, so stable order
    if len(tied) == 1:
        return tied[0]
    return max(tied, key=lambda index: _unassigned_neighbours(state, index))  # max keeps the first of equals


def _unassigned_neighbours(state: SearchState, slot_index: int) -> int:
    """How many unassigned slots the slot is constrained with: its degree in what's left of the problem."""
    return sum(1 for neighbour in state.problem.neighbours[slot_index] if state.assigned[neighbour] is None)


class _Search:
    """One run of the search: the state, and how far the search has got."""

    def __init__(self, problem: Problem) -> None:
        """
        :param problem: Problem
        """
        self.problem = problem
        self.state = SearchState(problem)
        self.filled = 0
        self.deepest = -1
        self.stuck_slot: Slot | None = None

    def search(self) -> bool:
        """
        Fill the remaining slots, recursively
        :return: True once every slot is assigned (the state then holds the schedule); False if no assignment of
        the remaining slots is legal, with the state restored to what it was
        """
        slot_index = choose_slot(self.state)
        if slot_index is None:
            return True
        if self.filled > self.deepest:
            self.deepest, self.stuck_slot = self.filled, self.problem.slots[slot_index]
        for worker in self.state.domains[slot_index]:  # domains are in input order: the order workers are tried in
            changes = self.state.assign(slot_index, worker)
            self.filled += 1
            if changes.emptied is None and self.search():
                return True
            self.state.undo(changes)
            self.filled -= 1
        return False


def find_first_schedule(problem: Problem) -> SearchResult:
    """
    Search for a legal schedule
    :param problem: Problem
    :return: the first legal schedule found (deterministically: slots are chosen by choose_slot and workers are
    tried in input order), or the point at which the search got stuck if there is none
    """
    run = _Search(problem)
    if run.search():
        return SearchResult(tuple(run.state.assigned), run.filled, None)
    return SearchResult(None, run.deepest, run.stuck_slot)
