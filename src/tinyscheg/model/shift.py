from __future__ import annotations
from tinyscheg.timing.datetime_range import DateTimeRange
from typing import List, Dict, Tuple, Optional
from tinyscheg.model.post import Post
from tinyscheg.model.worker import Worker
from datetime import timedelta, datetime

class Slot:
    """Representing a single schedule slot.
    In the schedule, a post is divided into shifts, which represent the state of this post at a certain time range
    Such a shift is a group of slots.
    For example, a \"front gate\" post that needs to be manned by two people at all times, one of which must be
    a supervisor and whose shift length is 2 hours, will have 2 slots for every 2-hour shifts, one for a supervisor
    and the other for the additional worker"""

    # static variables
    DEFAULT_MIN_REST = 6 # Default minimum rest period in hours, any post that are less than <min_rest> hours apart
                         # (including overlap) will have a binary difference constraint between them
    iteration_ticker = 0 # global iteration tracker, compared with each slot's last_iteration
    worker_list = []  # full domain for slots, each slot will copy and prune this list to fit its constraints.
                      # must be initialized before initializing any Slot object

    def __init__(self, time: DateTimeRange, role: str, post: Post):
        """
        Create a new schedule slot that fits a single worker of the appropriate role.
        This constructor performs unary constraint pruning and the resulting domain will reflect this.
        This constructor generates a Slot with NO binary constraints, which must be generated after the fact.
        :param time: DateTimeRange representing date-time period of this slot.
                    all workers with an unavailability period that overlaps time are pruned from the domain.
        :param role: Required role for this slot, all workers without this role are pruned from the domain.
                     if set to None, all workers may fill this Slot.
        :param post: Parent post this slot belongs to.
        """
        self.time = time
        self.post = post
        self.assigned = None
        self.diff_constrained = set() # set of other Slots this slot is diff constrained with
        self.same_shift = set() # set of other Slots which, along with this Slot, make up a single shift
        self.last_iteration = 0 # if last_iteration < iteration_ticker, this slot hasn't been checked
                                # in the current iteration routine
        self.unassigned_constraints = 0 # number of slots constrained to this slot which are unassigned
        # build domain
        self.domain = []
        for worker in Slot.worker_list:
            if worker.is_available(time) and worker.has_role(role):
                self.domain.append(worker)
                # TODO: report to worker about his inclusion in a domain
        # TODO: domain may need to be sorted in a way that's beneficial for the SCP algorithm

    def __lt__(self, other):
        if not isinstance(Slot, other):
            return NotImplemented
        return self.time < other.time

    def __eq__(self, other):
        if not isinstance(Slot, other):
            return NotImplemented
        return self.time == other.time

    def find_time_constraints(self, slots: List[Slot], min_rest: timedelta) -> None:
        """
        Create a diff constraint between this Slot and any Slot in the input list that is time constrained.
        (either at the same time or within the same min_rest range)
        Constraints are created both in this Slot and in the other Slot the constraint applies to
        :param slots: a list of Slots **sorted by time** beginning with overlapping time
        :param min_rest: datetime.timedelta object representing minimum rest period between two assignments
        """
        padded_time = self.time.pad(min_rest)
        for other_slot in slots:
            if not padded_time.overlaps(other_slot.time):
                # since the list begins with overlapping time and is ordered by start time and then end time,
                # if other_slot's time doesn't overlap with padded_time, no subsequent slot will overlap.
                return
            self.diff_constrained.add(other_slot)
            self.unassigned_constraints += 1
            other_slot.diff_constrained.add(self)
            other_slot.unassigned_constraints += 1

    @staticmethod
    def gen_time_constraints(slots: List[Slot], min_rest:float = DEFAULT_MIN_REST) -> None:
        """
        Generate time-based binary constraints between all slots in the input
        :param slots: List of Slot objects sorted by time (DateTimeRange)
        :param min_rest: minimum rest period in hours, defaults to DEFAULT_MIN_REST (6)
        """
        to_check = slots.copy()
        rest_delta = timedelta(0,0,0,0,0, min_rest)
        while to_check:
            current_slot = to_check.pop(0)
            current_slot.find_time_constraints(to_check, rest_delta)

    @staticmethod
    def set_same_shift(slots: List[Slot]) -> None:
        for i in range(len(slots)):
            slots[i].same_shift = set(slots[:i] + slots[i+1:])

    def propagate_constraint(self, to_remove: Worker) -> bool:
        """
        propagate a constraint following the removal of a worker from a slot's domain
        Should this Slot's domain become empty, this slot (and by extension the schedule) becomes **unsatisfiable**
        :param to_remove: Worker to remove from domain
        :return: True if the slot remains satisfiable, False otherwise
        """
        if self.assigned or self.last_iteration == Slot.iteration_ticker:
            # skip propagation if this slot has an assigned worker or if it was already checked in this iteration
            return True
        try: # remove the worker from the domain
            self.diff_constrained.remove(to_remove)
        except KeyError:
            # to_remove is not in the domain, mark slot as checked and stop propagation
            self.last_iteration = Slot.iteration_ticker
            return True
        if not self.domain: # if domain is empty (we checked previously it is unassigned)
            return False
        if len(self.domain) == 1: # if one worker remains in domain, assign it
            return self.assign(self.domain.pop())
            # further constraint propagation will be called by assign
        return True

    # TODO: define 'assign' and have it make use of constraint propagation
    def assign(self, worker: Worker) -> bool:
        """
        assign a worker to this slot, triggering constraint propagation.
        Should the constraint propagation triggered by this assignment yield a slot with an empty domain,
        the slot (and by extension the schedule) will become _unsatisfiable_
        If worker is not part of this Slot's domain, will raise a KeyError
        :param worker: Worker to assign to this slot
        :return: True if the schedule remains satisfiable after this assignment, False otherwise
        """
        if worker not in self.domain:
            raise KeyError("worker is not in this Slot's domain")
        # TODO: call on scoring classes and functions as part of the assignment
        # TODO: notify Trail of actions taken here, so that they may be reversed
        # TODO: update unassigned_constraints on all constrained slots

    def csp_lt(self, other: Slot) -> bool:
        """
        Alternative less-than comparison based on CSP heuristics.
        The primary criteria is MRV and Degree Heuristic is used as a tie-breaker.
        :param other: Slot object
        :return: True if self's domain is smaller than other's (MRV), or if the domains are of equal size
                 and self has more unassigned slots constrained to it than the other. (Degree Heuristic)
        """
        if len(self.domain) < len(other.domain):
            return True
        if len(self.domain) == len(other.domain):
            return self.unassigned_constraints > other.unassigned_constraints
        return False