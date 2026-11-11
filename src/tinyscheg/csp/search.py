"""Backtracking search with forward checking: for the first legal schedule, or the best one by branch and bound."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tinyscheg.csp.problem import Problem
from tinyscheg.csp.state import SearchState
from tinyscheg.model.shift import Slot
from tinyscheg.scoring.constants import ScoringConstants
from tinyscheg.scoring.penalty import Penalty, score


@dataclass(frozen=True, slots=True)
class SearchResult:
    """
    The outcome of a search.
    assignment holds a worker index per slot, or is None if no legal schedule exists. deepest is the most slots the
    search had filled at once, and stuck_slot the slot it had to fill next at that point (None if it found a
    schedule), for reporting where an infeasible input got stuck (ADR 0020). penalty is the schedule's penalty when
    the search looked for the best schedule (None otherwise, or if there is none). nodes counts the (partial)
    schedules the search visited, and pruned the branches it cut off because they couldn't beat the pocket.
    """
    assignment: tuple[int, ...] | None
    deepest: int
    stuck_slot: Slot | None
    penalty: Penalty | None = None
    nodes: int = 0
    pruned: int = 0


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
    """
    One run of the search: the state, how far the search has got and, when looking for the best schedule, the
    pocket (the best complete schedule found so far, ADR 0004)
    """

    def __init__(self, problem: Problem, constants: ScoringConstants | None = None, prune: bool = True,
                 on_improvement: Callable[[Penalty], None] | None = None) -> None:
        """
        :param problem: Problem
        :param constants: ScoringConstants to look for the best schedule with; None to stop at the first legal one
        :param prune: False to visit every branch even when it can't beat the pocket (for testing the pruning)
        :param on_improvement: called with the new pocket's penalty whenever a better schedule is found, or None
        """
        self.problem = problem
        self.state = SearchState(problem)
        self.constants = constants
        self.prune = prune
        self.filled = 0
        self.deepest = -1
        self.stuck_slot: Slot | None = None
        self.pocket: tuple[int, ...] | None = None
        self.pocket_penalty: Penalty | None = None
        self.nodes = 0
        self.pruned = 0
        self.on_improvement = on_improvement

    def search(self) -> bool:
        """
        Fill the remaining slots, recursively
        :return: True to stop the search: when looking for the first legal schedule, once every slot is assigned
        (the state then holds the schedule). False otherwise, with the state restored to what it was: when looking
        for the first schedule, no assignment of the remaining slots is legal; when looking for the best, this
        branch has been searched (or pruned), and the pocket holds the best schedule found so far
        """
        self.nodes += 1
        if self._cannot_beat_pocket():
            self.pruned += 1
            return False
        slot_index = choose_slot(self.state)
        if slot_index is None:
            return self._complete()
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

    def _cannot_beat_pocket(self) -> bool:
        """
        True if the current (partial) schedule's penalty is already at least the pocket's. Filling more slots never
        lowers the penalty, and ties keep the pocket, so nothing in this branch can replace it (ADR 0017).
        """
        if self.constants is None or self.pocket_penalty is None or not self.prune:
            return False
        return score(self.constants, self.state.assigned).total >= self.pocket_penalty.total

    def _complete(self) -> bool:
        """
        Handle a complete, legal schedule
        :return: True to stop at the first schedule; when looking for the best, put it in the pocket if it's better
        than the pocket's (on equal penalties the one found first stays), and return False to keep searching
        """
        if self.constants is None:
            return True
        penalty = score(self.constants, self.state.assigned)
        if self.pocket_penalty is None or penalty.total < self.pocket_penalty.total:
            self.pocket, self.pocket_penalty = tuple(self.state.assigned), penalty
            if self.on_improvement is not None:
                self.on_improvement(penalty)
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
        return SearchResult(tuple(run.state.assigned), run.filled, None, nodes=run.nodes)
    return SearchResult(None, run.deepest, run.stuck_slot, nodes=run.nodes)


def find_best_schedule(problem: Problem, constants: ScoringConstants, prune: bool = True,
                       on_improvement: Callable[[Penalty], None] | None = None) -> SearchResult:
    """
    Search for the best legal schedule by branch and bound: every branch is searched unless its penalty is already
    at least the pocket's. The search runs to the end, however long that takes.
    :param problem: Problem
    :param constants: ScoringConstants, built for the same input
    :param prune: False only for testing: search every branch, to check that pruning loses nothing
    :param on_improvement: called with the penalty of each better schedule as it's found (e.g. to show progress);
    None for no calls
    :return: the legal schedule with the lowest penalty and its penalty (deterministically: of equally good
    schedules, the first found), or the point at which the search got stuck if there is none
    """
    run = _Search(problem, constants, prune, on_improvement)
    run.search()
    if run.pocket is None:
        return SearchResult(None, run.deepest, run.stuck_slot, nodes=run.nodes, pruned=run.pruned)
    return SearchResult(run.pocket, len(problem.slots), None, run.pocket_penalty, run.nodes, run.pruned)
