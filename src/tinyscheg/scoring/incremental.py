"""
Incremental scoring (ADR 0027): running totals of the penalty and its lower bound, updated by what each assignment
changes and rolled back on backtracking by restoring saved values. They only steer the search (the value order, and
pruning away from near-ties); what decides its result is scored from scratch with tinyscheg.scoring.penalty, which
also defines what these totals must equal, up to rounding.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass

from tinyscheg.scoring.constants import ScoringConstants
from tinyscheg.scoring.penalty import (_assigned_load, _slots_by_worker, _water_level, likes_total, normalized_likes,
                                       pair_like_value, rest_deficit, rest_penalty, shift_likes_lower_bound,
                                       workload_total)


@dataclass(frozen=True, slots=True)
class _Saved:
    """Everything one assignment changed in an IncrementalScore, as it was before, so that undo restores it exactly."""
    likes: float
    workload: float
    rest: float
    likes_bound: float
    remaining: float
    worker: int                                  # the worker assigned
    load: float                                  # their load before
    position: int                                # where the slot went among their slots
    caps: tuple[tuple[int, float], ...]          # (worker, cap before), for every cap changed
    shift_bounds: tuple[tuple[int, float], ...]  # (shift index, its likes look-ahead before), for every one changed


class IncrementalScore:
    """
    The running totals of one search: the likes total over the filled pairs, the workload and rest totals, and each
    worker's load and slots in time order; and for the lower bound, each shift's likes look-ahead and each
    worker's workload cap. assign updates them, undo restores them; both must be called in step with the search's
    own assignments, the latest assignment undone first.
    """

    def __init__(self, constants: ScoringConstants, assignment: Sequence[int | None],
                 domains: Sequence[Sequence[int]]) -> None:
        """
        :param constants: ScoringConstants of the run
        :param assignment: the search's assignment (a worker index per slot, or None), as it is when the search starts:
        empty, or with the history filled in (ADR 0031); it's read, not changed, so it must be the search's own list
        :param domains: the search's current domains, likewise read as the search changes them
        """
        self.constants = constants
        self.assignment = assignment
        self.domains = domains
        # the totals of what's filled already, computed from scratch; from here on they're kept up to date
        self.likes = likes_total(constants, assignment)        # over filled pairs, before normalizing
        self.workload = workload_total(constants, assignment)  # the sum of av * (load / av) ** p, before normalizing
        self.rest = rest_penalty(constants, assignment)        # the sum of deficit * rest_unit / M_w
        self.load = _assigned_load(constants, assignment)
        self.slots: list[list[int]] = _slots_by_worker(constants, assignment)
        self.shift_bounds = [shift_likes_lower_bound(constants, shift, assignment, domains)
                             for shift in constants.shifts]
        self.likes_bound = 0.0
        for shift_bound in self.shift_bounds:  # a plain loop rounds the same on every interpreter, like fsum
            self.likes_bound += shift_bound
        self.caps = [0.0] * len(constants.workers)
        self.remaining = 0.0
        for slot, domain in enumerate(domains):
            if assignment[slot] is None:
                self.remaining += constants.slot_load[slot]
                for worker in domain:
                    self.caps[worker] += constants.slot_load[slot]
        self._saved: list[_Saved] = []

    # --- the value order ---

    def total(self) -> float:
        """The current (partial) schedule's total penalty."""
        return self._total(self.likes, self.workload, self.rest)

    def cost_if(self, slot: int, worker: int) -> float:
        """
        The total penalty the current schedule would have with the worker in the (unfilled) slot
        :param slot: int
        :param worker: int
        :return: the total, as score() would give it, up to rounding
        """
        return self._total(self.likes + self._likes_delta(slot, worker),
                           self.workload + self._workload_delta(worker, slot),
                           self.rest + self._rest_delta(worker, slot)[0])

    # --- the lower bound ---

    def bound(self) -> float:
        """The lower bound on every completion of the current schedule, as lower_bound() would give it, up to
        rounding."""
        constants = self.constants
        parameters = constants.parameters
        likes = normalized_likes(constants, self.likes_bound)
        return (parameters.likes_weight * likes + parameters.workload_weight * self._workload_bound()
                + parameters.rest_weight * self.rest)

    def _workload_bound(self) -> float:
        """workload_lower_bound, from the running loads, caps and remaining load."""
        constants = self.constants
        if constants.workload_unit == 0:
            return 0.0
        power = constants.parameters.workload_power
        pool = [(self.load[index] / worker.availability, worker.availability,
                 (self.load[index] + self.caps[index]) / worker.availability)
                for index, worker in enumerate(constants.workers) if worker.availability > 0]
        level = _water_level(pool, self.remaining)
        filled = 0.0
        for ratio, availability, highest in pool:  # a plain loop rounds the same on every interpreter, like fsum
            filled += availability * min(max(ratio, level), highest) ** power
        return filled / constants.workload_unit

    # --- assigning and undoing ---

    def assign(self, slot: int, worker: int, narrowed: Sequence[tuple[int, Sequence[int]]]) -> None:
        """
        Update the totals for an assignment the search has just made
        :param slot: int, the slot just assigned (already in the search's assignment)
        :param worker: int, its worker
        :param narrowed: (slot, domain before) for each domain the assignment narrowed, as the search's change record
        lists them (a slot may appear more than once; its first entry holds the domain from before the assignment)
        """
        constants = self.constants
        before: dict[int, Sequence[int]] = {}
        for narrowed_slot, domain in narrowed:
            before.setdefault(narrowed_slot, domain)
        changed_shifts = sorted({constants.slots[slot].shift_index}
                                | {constants.slots[other].shift_index for other in before})
        old_shift_bounds = tuple((shift, self.shift_bounds[shift]) for shift in changed_shifts)
        old = (self.likes, self.workload, self.rest, self.likes_bound, self.remaining, self.load[worker])
        # the scores, from the deltas, taken before the worker's load and slots change
        rest_delta, position = self._rest_delta(worker, slot)
        self.likes += self._likes_delta(slot, worker)
        self.workload += self._workload_delta(worker, slot)
        self.rest += rest_delta
        self.load[worker] += constants.slot_load[slot]
        self.slots[worker].insert(position, slot)
        # the workload look-ahead: the slot's load is no longer to be spread, nor in anyone's cap; and a worker dropped
        # from a narrowed domain can no longer take that slot's load
        caps_before: dict[int, float] = {}
        self.remaining -= constants.slot_load[slot]
        for candidate in self.domains[slot]:
            caps_before.setdefault(candidate, self.caps[candidate])
            self.caps[candidate] -= constants.slot_load[slot]
        for narrowed_slot, domain in before.items():
            current = set(self.domains[narrowed_slot])
            for dropped in domain:
                if dropped not in current:
                    caps_before.setdefault(dropped, self.caps[dropped])
                    self.caps[dropped] -= constants.slot_load[narrowed_slot]
        # the likes look-ahead: only the shifts with a slot assigned or narrowed can change
        for shift in changed_shifts:
            new = shift_likes_lower_bound(constants, constants.shifts[shift], self.assignment, self.domains)
            self.likes_bound += new - self.shift_bounds[shift]
            self.shift_bounds[shift] = new
        likes, workload, rest, likes_bound, remaining, load = old
        self._saved.append(_Saved(likes, workload, rest, likes_bound, remaining, worker, load, position,
                                  tuple(caps_before.items()), old_shift_bounds))

    def undo(self) -> None:
        """Undo the latest assignment, restoring every total exactly as it was."""
        saved = self._saved.pop()
        self.likes, self.workload, self.rest = saved.likes, saved.workload, saved.rest
        self.likes_bound, self.remaining = saved.likes_bound, saved.remaining
        self.load[saved.worker] = saved.load
        del self.slots[saved.worker][saved.position]
        for capped, cap in saved.caps:
            self.caps[capped] = cap
        for shift, value in saved.shift_bounds:
            self.shift_bounds[shift] = value

    # --- the parts ---

    def _total(self, likes: float, workload: float, rest: float) -> float:
        """The weighted total of the raw running totals, normalized as score() normalizes them."""
        constants = self.constants
        parameters = constants.parameters
        normalized_workload = workload / constants.workload_unit if constants.workload_unit else 0.0
        normalized = normalized_likes(constants, likes)
        return (parameters.likes_weight * normalized + parameters.workload_weight * normalized_workload
                + parameters.rest_weight * rest)

    def _likes_delta(self, slot: int, worker: int) -> float:
        """What putting the worker in the slot adds to the likes total: their pairings with the shift's other filled
        slots."""
        shift = self.constants.shifts[self.constants.slots[slot].shift_index]
        others = len(shift.slots) - 1
        if others == 0:
            return 0.0
        total = 0.0
        for other in shift.slots:
            partner = self.assignment[other.index]
            if other.index != slot and partner is not None:
                total += pair_like_value(self.constants, worker, partner) / others
        return total

    def _workload_delta(self, worker: int, slot: int) -> float:
        """What giving the worker the slot adds to the sum of av * (load / av) ** p."""
        availability = self.constants.workers[worker].availability
        if availability <= 0:
            return 0.0
        power = self.constants.parameters.workload_power
        load = self.load[worker]
        return availability * (((load + self.constants.slot_load[slot]) / availability) ** power
                               - (load / availability) ** power)

    def _rest_delta(self, worker: int, slot: int) -> tuple[float, int]:
        """
        What giving the worker the slot adds to the rest total, and where the slot goes among their slots
        :return: (the change in deficit * rest_unit / M_w, the slot's position in the worker's slots)
        """
        slots = self.slots[worker]
        position = bisect.bisect_left(slots, slot)
        worst = self.constants.workers[worker].worst_deficit
        if worst == 0:
            return 0.0, position
        earlier = slots[position - 1] if position > 0 else None
        later = slots[position] if position < len(slots) else None
        change = 0.0
        if earlier is not None:
            change += rest_deficit(self.constants, earlier, slot)
        if later is not None:
            change += rest_deficit(self.constants, slot, later)
        if earlier is not None and later is not None:
            change -= rest_deficit(self.constants, earlier, later)
        return change * self.constants.rest_unit / worst, position
