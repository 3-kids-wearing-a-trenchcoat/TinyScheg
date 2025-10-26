import DateTimeRange

class Worker:
    """
    Represents a single worker that can be assigned in the schedule.
    Contains the worker's name, role list, like list, dislike list and unavailability list.
    """
    def __init__(self, name, roles=None, unavailable=None, likes=None, dislikes=None):
        self.name = name
        if roles is None:self.roles = []
        else: self.roles = roles
        if likes is None: likes = []
        else: self.likes = likes
        if dislikes is None : self.dislikes = []
        else: self.dislikes = dislikes
        self.unavailable = sorted([DateTimeRange.parse_range(pair) for pair in unavailable])
        # TODO: add variables relevant to the CSP algorithm

    # TODO: Implement __lt__ and __eq__ when it's clear how workers should be ordered for CSP

    def likes_worker(self, other):
        if not isinstance(other, Worker):
            raise TypeError("Expecting a Worker as other")
        return self.likes.contains(other)

    def dislikes_worker(self, other):
        if not isinstance(other, Worker):
            raise TypeError("Expecting a Worker as other")
        return self.dislikes.contains(other)

    def _prune_unavailability_list(self, other_time):
        """
        Remove from the unavailability list all ranges which end before other_time.
        other_time can be either a datetime.datetime object or a DateTimeRange object.
        In the latter case, DateTimeRange's start value will be used.
        This reduces the total amount of ranges that need to be checked while removing workers from shift domains.
        :param other_time: datetime.datetime object or DateTimeRange object
        :return: None
        """
        while self.unavailable and self.unavailable[0].is_before(other_time):
            self.unavailable.pop(0)

    def is_available(self, period: DateTimeRange.DateTimeRange):
        """Return True if the given period does not overlap with this worker's unavailability.
        Otherwise, return False"""
        for unavailable_time in self.unavailable:
            if unavailable_time.overlaps(period):
                return False
        return True

    def has_role(self, required_role: str):
        """Return True if the worker has the input required role.
        Otherwise, return False."""
        return required_role in self.roles