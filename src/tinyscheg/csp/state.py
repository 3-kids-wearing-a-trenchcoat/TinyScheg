"""
The search state: the domains and assignments of all slots, and the change records used to undo assignments
(ADR 0016).
"""
from __future__ import annotations

from dataclasses import dataclass

from tinyscheg.csp.problem import Problem


@dataclass(frozen=True, slots=True)
class Changes:
    """
    Everything one assignment changed, so that it can be undone exactly.
    saved_domains holds (slot index, domain before the change) pairs, in the order the domains were changed.
    emptied is the index of a slot whose domain became empty, or None; forward checking stops there.
    """
    slot_index: int
    saved_domains: tuple[tuple[int, tuple[int, ...]], ...]
    emptied: int | None


class SearchState:
    """
    The changing part of the search: for each slot, the workers who can still fill it, and the assigned worker.
    Domains are immutable tuples in ascending worker order; changing one replaces it, so undo can put back the
    saved tuple rather than reverse an operation.
    """

    def __init__(self, problem: Problem) -> None:
        """
        :param problem: Problem, the fixed description of the CSP; the state starts from its domains
        """
        self.problem = problem
        self.domains: list[tuple[int, ...]] = list(problem.domains)
        self.assigned: list[int | None] = [None] * len(problem.slots)

    def assign(self, slot_index: int, worker: int) -> Changes:
        """
        Assign a worker to a slot, then forward check: remove the worker from the domain of every unassigned slot
        constrained with this one
        :param slot_index: int, an unassigned slot
        :param worker: int, a worker index in the slot's domain
        :return: the Changes made; if a domain became empty, emptied says which, and the remaining neighbours were
        left unchanged
        """
        if self.assigned[slot_index] is not None:
            raise ValueError(f"slot {slot_index} is already assigned")
        if worker not in self.domains[slot_index]:
            raise ValueError(f"worker {worker} is not in the domain of slot {slot_index}")
        self.assigned[slot_index] = worker
        saved = []
        emptied = None
        for neighbour in self.problem.neighbours[slot_index]:
            domain = self.domains[neighbour]
            if self.assigned[neighbour] is not None or worker not in domain:
                continue
            saved.append((neighbour, domain))
            self.domains[neighbour] = tuple(other for other in domain if other != worker)
            if not self.domains[neighbour]:
                emptied = neighbour
                break  # this assignment is a dead end; there's no point in checking further
        return Changes(slot_index, tuple(saved), emptied)

    def undo(self, changes: Changes) -> None:
        """
        Undo an assignment, putting back exactly what it changed
        :param changes: Changes, as returned by the latest assign that hasn't been undone yet
        :return: None
        """
        for neighbour, domain in reversed(changes.saved_domains):
            self.domains[neighbour] = domain
        self.assigned[changes.slot_index] = None
