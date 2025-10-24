import DateTimeRange
from typing import List, Dict, Tuple, Optional

class Post:
    """Defining a post that needs to be manned throughout the schedule.
    A Post is a kind of template from which we generate a list of individual shifts.
    For example, a \"front gate\" post that needs to be manned 24/7 by a single person for 2-hour shifts will
    generate 12 \"front gate\" shifts, each representing a 2-hour period."""

    def __init__(self, name: str, length: int, roles: Dict[str, int], time=None, variations=None):
        """
        Initialize a Post object (representing a single variation of a post)
        :param name: post name
        :param length: shift length
        :param roles: dict (str: int) specifying how many workers of each role are needed
        :param time: DateTimeRange specifying activity period for this post, if left empty, this post is always active
        :param variations: DateTimeRange-based variations on this Post, may be left empty.
        (assuming time-based ranges have already been converted to a series of datetime ranges)
        Expected form for variations is:
         Dict[DateTimeRange, Tuple[int(duration), Dict(roles)[str(role name), int(num of workers of this role)]]]
        """
        if time and not isinstance(DateTimeRange, time): # accept only DateTimeRange or None in time
            raise TypeError("time must be None or a DateTimeRange object")
        if variations and not isinstance(Dict[DateTimeRange, Tuple[int, Dict[str, int]]], variations):
            raise TypeError("variations must be None or a dict mapping DateTimeRange to duration and a role dict")
        self.name, self.length, self.roles, self.time, self.variations = name, length, roles, time, variations

    # TODO: implement gen_shift_list