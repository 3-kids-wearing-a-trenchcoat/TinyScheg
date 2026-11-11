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

    def next_slot(self) -> int | None:
        """The next slot to fill: the first unassigned one in stable order, or None if all are assigned."""
        for index, worker in enumerate(self.state.assigned):
            if worker is None:
                return index
        return None

    def search(self) -> bool:
        """
        Fill the remaining slots, recursively
        :return: True once every slot is assigned (the state then holds the schedule); False if no assignment of
        the remaining slots is legal, with the state restored to what it was
        """
        slot_index = self.next_slot()
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
    :return: the first legal schedule found (deterministically: slots are filled in stable order and workers are
    tried in input order), or the point at which the search got stuck if there is none
    """
    run = _Search(problem)
    if run.search():
        return SearchResult(tuple(run.state.assigned), run.filled, None)
    return SearchResult(None, run.deepest, run.stuck_slot)
