"""Backtracking search with forward checking: for the first legal schedule, or the best one by branch and bound."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tinyscheg.csp.problem import Problem
from tinyscheg.csp.state import SearchState
from tinyscheg.model.shift import Slot
from tinyscheg.scoring.constants import ScoringConstants
from tinyscheg.scoring.incremental import IncrementalScore
from tinyscheg.scoring.penalty import Penalty, lower_bound, score

# Pruning compares the incremental bound with the pocket's penalty, deciding from scratch only within this margin of a
# tie (ADR 0027): far above the rounding differences of incremental scoring (about 1e-14), far below any difference
# that matters
NEAR_TIE_MARGIN = 1e-9
# How often the search reports its progress, in nodes (ADR 0035): rarely enough to cost nothing noticeable, often
# enough that a report comes every small fraction of a second
PROGRESS_INTERVAL_NODES = 4096


@dataclass(frozen=True, slots=True)
class SearchProgress:
    """
    How far a search has got (ADR 0035): finished is the share of the search space finished so far, from 0 to 1 (each
    node's weight split equally among its children, a finished branch's weight added), and nodes the nodes visited.
    """
    finished: float
    nodes: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    """
    The outcome of a search.
    assignment holds a worker index per slot, or is None if no legal schedule exists. deepest is the most slots the
    search had filled at once, and stuck_slot the slot it had to fill next at that point (None if it found a
    schedule), for reporting where an infeasible input got stuck (ADR 0020). penalty is the schedule's penalty when
    the search looked for the best schedule (None otherwise, or if there is none). nodes counts the (partial)
    schedules the search visited, and pruned the branches it cut off because they couldn't beat the pocket.
    complete is False for a best-schedule search stopped by Ctrl+C (ADR 0035): assignment is then the best schedule
    found so far, not proven the best (None if none was found yet), and finished the share of the search space it
    had finished; for a search that ran to the end, finished is 1.
    """
    assignment: tuple[int, ...] | None
    deepest: int
    stuck_slot: Slot | None
    penalty: Penalty | None = None
    nodes: int = 0
    pruned: int = 0
    complete: bool = True
    finished: float = 1.0


def choose_slot(state: SearchState) -> int | None:
    """
    Choose the next slot to fill (ADR 0003): the unassigned slot with the fewest workers left in its domain (MRV);
    among those, the one constrained with the most other unassigned slots (degree); among those, the lowest index
    :param state: SearchState, the current domains and assignments
    :return: the index of the slot to fill next, or None if every slot is assigned
    """
    domains = state.domains
    smallest = -1
    tied: list[int] = []  # the unassigned slots with the smallest domain so far, ascending, so in stable order
    for index, worker in enumerate(state.assigned):
        if worker is not None:
            continue
        size = len(domains[index])
        if size < smallest or smallest < 0:
            smallest, tied = size, [index]
        elif size == smallest:
            tied.append(index)
    if not tied:
        return None
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
                 on_improvement: Callable[[Penalty], None] | None = None, incremental: bool = True,
                 on_progress: Callable[[SearchProgress], None] | None = None) -> None:
        """
        :param problem: Problem
        :param constants: ScoringConstants to look for the best schedule with; None to stop at the first legal one
        :param prune: False to visit every branch even when it can't beat the pocket (for testing the pruning)
        :param on_improvement: called with the new pocket's penalty whenever a better schedule is found, or None
        :param incremental: False to steer by scoring from scratch, as before ADR 0027 (for testing and comparing)
        :param on_progress: called with the search's progress every PROGRESS_INTERVAL_NODES nodes, or None
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
        self.on_progress = on_progress
        self.finished = 0.0  # the share of the search space finished (ADR 0035); it only observes the search
        self.scores = (IncrementalScore(constants, self.state.assigned, self.state.domains)
                       if constants is not None and incremental else None)
        # Cutting the tree into subtrees for the parallel search (ADR 0041): with cut_depth set, a branch reaching
        # that many assignments (or a complete schedule above it) isn't searched but recorded in cut, as its path of
        # (slot, worker) assignments, in order, and its share of the search space
        self.cut_depth: int | None = None
        self.cut: list[tuple[tuple[tuple[int, int], ...], float]] = []
        self.path: list[tuple[int, int]] = []  # the assignments made so far, kept only while cutting

    def search(self, weight: float = 1.0) -> bool:
        """
        Fill the remaining slots, recursively
        :param weight: this branch's share of the whole search space (1 at the root), split equally among the values
        tried for the next slot; added to self.finished once the branch is finished (ADR 0035)
        :return: True to stop the search: when looking for the first legal schedule, once every slot is assigned
        (the state then holds the schedule). False otherwise, with the state restored to what it was: when looking
        for the first schedule, no assignment of the remaining slots is legal; when looking for the best, this
        branch has been searched (or pruned), and the pocket holds the best schedule found so far
        """
        self.nodes += 1
        if self.on_progress is not None and self.nodes % PROGRESS_INTERVAL_NODES == 0:
            self.on_progress(SearchProgress(self.finished, self.nodes))
        if self._cannot_beat_pocket():
            self.pruned += 1
            self.finished += weight
            return False
        slot_index = choose_slot(self.state)
        if self.cut_depth is not None and (slot_index is None or self.filled == self.cut_depth):
            self.cut.append((tuple(self.path), weight))  # handed out whole; its share is finished where it's searched
            return False
        if slot_index is None:
            self.finished += weight
            return self._complete()
        if self.filled > self.deepest:
            self.deepest, self.stuck_slot = self.filled, self.problem.slots[slot_index]
        values = self._value_order(slot_index)
        if not values:
            self.finished += weight  # a dead end: no worker left for the slot
        share = weight / len(values) if values else 0.0
        for worker in values:
            changes = self.state.assign(slot_index, worker)
            self.filled += 1
            if changes.emptied is None:
                if self.scores is not None:
                    self.scores.assign(slot_index, worker, changes.saved_domains)
                if self.cut_depth is not None:
                    self.path.append((slot_index, worker))
                stop = self.search(share)
                if self.cut_depth is not None:
                    self.path.pop()
                if self.scores is not None:
                    self.scores.undo()
                if stop:
                    return True
            else:
                self.finished += share  # forward checking emptied a domain: nothing to search below
            self.state.undo(changes)
            self.filled -= 1
        return False

    def start_from(self, path: Sequence[tuple[int, int]]) -> None:
        """
        Make the assignments of a path, as the search made them on the way to a subtree (ADR 0041): in the same order,
        so that the incremental totals, and with them the order workers are tried in below, are exactly the same
        :param path: (slot, worker) assignments, as cut records them
        """
        for slot_index, worker in path:
            changes = self.state.assign(slot_index, worker)
            self.filled += 1
            if self.scores is not None:
                self.scores.assign(slot_index, worker, changes.saved_domains)

    def _value_order(self, slot_index: int) -> list[int]:
        """
        The order to try a slot's workers in. For the first legal schedule, input order. For the best, cheapest first
        (ADR 0024): by the penalty of the schedule with the worker assigned (kept incrementally, ADR 0027), then input
        order. That changes only how
        soon good schedules are found, and so how much is pruned; of equally good schedules, the first found in this
        order is kept.
        """
        domain = self.state.domains[slot_index]
        if self.constants is None:
            return list(domain)
        if self.scores is not None:
            incremental_costs = {worker: self.scores.cost_if(slot_index, worker) for worker in domain}
            return sorted(domain, key=lambda worker: (incremental_costs[worker], worker))
        assigned = self.state.assigned
        costs = {}
        try:
            for worker in domain:
                assigned[slot_index] = worker  # scored in place, then put back
                costs[worker] = score(self.constants, assigned).total
        finally:
            assigned[slot_index] = None
        return sorted(domain, key=lambda worker: (costs[worker], worker))

    def _cannot_beat_pocket(self) -> bool:
        """
        True if no completion of the current (partial) schedule can beat the pocket: its lower bound (ADR 0024: the
        rest penalty so far, with the lowest likes and workload penalties the current domains could still give) is
        already at least the pocket's. The bound is kept incrementally, and computed from scratch only near a tie
        (ADR 0027), so the decision is the same as from scratch.
        Ties keep the pocket, so a branch that can at best tie is pruned too (ADR 0017).
        """
        if self.constants is None or not self.prune:
            return False
        pocket = self._pocket_total()
        if pocket is None:
            return False
        if self.scores is not None:
            # ADR 0027: the incremental bound decides, unless it's within NEAR_TIE_MARGIN of the pocket's penalty
            bound = self.scores.bound()
            if bound >= pocket + NEAR_TIE_MARGIN:
                return True
            if bound <= pocket - NEAR_TIE_MARGIN:
                return False
        exact = lower_bound(self.constants, self.state.assigned, self.state.domains)
        return exact >= pocket if self._ties_lose() else exact > pocket

    def _pocket_total(self) -> float | None:
        """The penalty a schedule must beat, or None while there's nothing to beat."""
        return self.pocket_penalty.total if self.pocket_penalty is not None else None

    def _ties_lose(self) -> bool:
        """Whether a schedule with exactly the pocket's penalty loses to it: always here (ADR 0017), not always in a
        subtree of the parallel search (ADR 0041)."""
        return True

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
                       on_improvement: Callable[[Penalty], None] | None = None,
                       incremental: bool = True, on_progress: Callable[[SearchProgress], None] | None = None,
                       keep_best_on_interrupt: bool = False) -> SearchResult:
    """
    Search for the best legal schedule by branch and bound: every branch is searched unless its penalty is already
    at least the pocket's. The search runs to the end, however long that takes, unless stopped with Ctrl+C.
    :param problem: Problem
    :param constants: ScoringConstants, built for the same input
    :param prune: False only for testing: search every branch, to check that pruning loses nothing
    :param on_improvement: called with the penalty of each better schedule as it's found (e.g. to show progress);
    None for no calls
    :param incremental: False only for testing and comparing: steer by scoring from scratch (ADR 0027)
    :param on_progress: called with the search's progress every PROGRESS_INTERVAL_NODES nodes (ADR 0035); None for
    no calls
    :param keep_best_on_interrupt: True to return the best schedule found so far when Ctrl+C stops the search, marked
    as not complete (ADR 0035); False to let KeyboardInterrupt through
    :return: the legal schedule with the lowest penalty and its penalty (deterministically: of equally good
    schedules, the first found), or the point at which the search got stuck if there is none
    """
    run = _Search(problem, constants, prune, on_improvement, incremental, on_progress)
    try:
        run.search()
    except KeyboardInterrupt:
        if not keep_best_on_interrupt:
            raise
        return _interrupted(run, constants)
    if run.pocket is None:
        return SearchResult(None, run.deepest, run.stuck_slot, nodes=run.nodes, pruned=run.pruned)
    return SearchResult(run.pocket, len(problem.slots), None, run.pocket_penalty, run.nodes, run.pruned)


def _interrupted(run: _Search, constants: ScoringConstants) -> SearchResult:
    """
    The result of a best-schedule search stopped by Ctrl+C: the best schedule found so far, if any, with its penalty
    recomputed from scratch (the interruption may have come between storing the pocket and its penalty)
    """
    pocket = run.pocket
    if pocket is None:
        return SearchResult(None, run.deepest, None, nodes=run.nodes, pruned=run.pruned, complete=False,
                            finished=run.finished)
    return SearchResult(pocket, len(run.problem.slots), None, score(constants, pocket), run.nodes, run.pruned,
                        complete=False, finished=run.finished)
