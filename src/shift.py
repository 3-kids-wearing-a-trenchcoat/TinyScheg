from __future__ import annotations
from DateTimeRange import DateTimeRange
from typing import List, Dict, Tuple, Optional
from Worker import Worker
from datetime import timedelta, datetime

class Post:
    """Defining a post that needs to be manned throughout the schedule.
    A Post is a kind of template from which we generate a list of individual shifts.
    For example, a \"front gate\" post that needs to be manned 24/7 by a single person for 2-hour shifts will
    generate 12 \"front gate\" shifts, each representing a 2-hour period."""

    def __init__(self, name: str, length: int, roles: Dict[str, int],
                 period:DateTimeRange|None=None,
                 variations:Dict[DateTimeRange, Tuple[int, Dict[str, int]]]|None=None):
        """
        Initialize a Post object (representing a single variation of a post)
        :param name: post name
        :param length: shift length
        :param roles: dict (str: int) specifying how many workers of each role are needed
        :param period: DateTimeRange specifying activity period for this post, if left empty, this post is always active
        :param variations: DateTimeRange-based variations on this Post, may be left empty.
        (assuming time-based ranges have already been converted to a series of datetime ranges)
        Expected form for variations is:
         Dict[DateTimeRange, Tuple[int(duration), Dict(roles)[str(role name), int(num of workers of this role)]]]
         It is assumed that each variation contains ALL variables and that filling in unspecified vars is done beforehand.
        """
        if not period:
            period = DateTimeRange.forever()
        elif not isinstance(DateTimeRange, period): # accept only DateTimeRange or None in time
            raise TypeError("time must be None or a DateTimeRange object")
        if not variations:
            variations = Dict()
        elif not isinstance(Dict[DateTimeRange, Tuple[int, Dict[str, int]]], variations):
            raise TypeError("variations must be None or a dict mapping DateTimeRange to duration and a role dict")
        self.name, self.length, self.roles, self.period, self.variations = name, length, roles, period, variations

    def get_variation(self, start_time: datetime) -> Tuple[int, Dict[str, int]] | None:
        """
        Find the post variation (including default) containing the start time and return it as a Tuple of key and value
        :param start_time: datetime.datetime object representing start time for a shift
        :return: (duration(int), Dict[role_name(str), required_workers(int)])
                 Returns None if Post isn't active at this start_time
        """
        if start_time >= self.period:
            return None # Post is no longer active
        for var_period in self.variations.keys():
            if var_period.in_range(start_time):
                return self.variations[var_period]
        return self.length, self.roles

    def gen_slot_list(self, period: DateTimeRange) -> List[Slot] | List[None]:
        """
        Generate a list of Slots according to this Post
        :param period: Schedule datetime range
        :return: list of Slot objects
        """
        output = []
        start = period.start
        while start < period.end:
            current_var = self.get_variation(start)
            if not current_var: # getting None from get_variation means we're out of this post's activity range
                break
            same_shift = []
            end = start + current_var[0]
            current_period = DateTimeRange(start, end)
            for role in current_var[1].keys():
                # for every role required by this shift...
                for i in range(current_var[1][role]):
                    # ...generate a number of slots equal to the required workers of that role
                    same_shift.append(Slot(current_period, role, self))
            Slot.set_same_shift(same_shift) # create same_shift association between the new slots
            output += same_shift # append the newly created slots into the output
            start = end # move on to next time period
        return output



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
            other_slot.diff_constrained.add(self)

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