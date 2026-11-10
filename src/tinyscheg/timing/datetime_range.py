import datetime as dt

class DateTimeRange:
    """
    A simple date-time range: [start, end) (inclusive start, exclusive end)
    Start and end must be datetime.datetime objects and start <= end.
    Both datetime objects are assumed to be timezone naive (timezones are not taken into account)
    """

    def __init__(self, start, end):
        """DateTimeRange constructor
        Requires *start* which is a datetime object representing the start of the range
        and *end*, which is either a datetime object representing the end
        or a timedelta object representing the length of the range from start."""
        if not isinstance(start, dt.datetime):
            raise TypeError("start must be a datetime.datetime instance")
        self.start = start
        if isinstance(end, dt.timedelta):
            self.end = start + end
        elif isinstance(end, dt.datetime):
            if start > end:
                raise ValueError("start must be before or equal to end")
            self.end = end
        else:
            raise TypeError("end must be a datetime.datetime instance or a datetime.timedelta instance")

    @property
    def duration(self) -> dt.timedelta:
        """return a datetime.timedelta of end - start"""
        return self.end - self.start

    def __eq__(self, other):
        if not isinstance(other, DateTimeRange):
            return NotImplemented
        return self.start == other.start and self.end == other.end

    def __lt__(self, other):
        if not isinstance(other, DateTimeRange):
            return NotImplemented
        return (self.start, self.end) < (other.start, other.end)

    def __gt__(self, other):
        if not isinstance(other, DateTimeRange):
            return NotImplemented
        return (self.start, self.end) > (other.start, other.end)

    def __ge__(self, other):
        if not isinstance(other, DateTimeRange):
            return NotImplemented
        return (self.start, self.end) >= (other.start, other.end)

    def __le__(self, other):
        if not isinstance(other, DateTimeRange):
            return NotImplemented
        return (self.start, self.end) <= (other.start, other.end)

    def __repr__(self):
        return "DateTimeRange ({!r} -> {!r})".format(self.start, self.end)

    def __hash__(self):
        return hash((self.start, self.end))

    def touches(self, other):
        """return True if one DateTimeRange start immediately as the other ends, return False otherwise"""
        if not isinstance(other, DateTimeRange):
            return NotImplemented
        return self.start == other.end or self.end == other.start

    def overlaps(self, other):
        if not isinstance(other, DateTimeRange):
            return NotImplemented
        return self.start <= other.end and other.start <= self.end and not self.touches(other)

    def in_range(self, other):
        """Return True if other is entirely contained within this DateTimeRange
        other may be either a DateTimeRange object or a datetime.datetime object"""
        if not isinstance(other, dt.datetime):
            if isinstance(other, DateTimeRange):
                return self.start <= other.start < self.end and self.start <= other.end < self.end
            return NotImplemented
        return self.start <= other < self.end

    def is_before(self, other):
        if isinstance(other, dt.datetime):
            return self.end < other
        elif isinstance(other, DateTimeRange):
            return self.end < other.start
        return NotImplemented

    def is_after(self, other):
        if isinstance(other, dt.datetime):
            return self.start > other
        elif isinstance(other, DateTimeRange):
            return self.start > other.end
        return NotImplemented

    def time_str(self):
        return "{!r} - {!r}".format(self.start.time(), self.end.time())

    def intersect(self, other):
        """Return an intersection of two DateTimeRange objects
        That is, a DateTimeRange contained within both self and other
        If the intersection is empty, returns None"""
        if not isinstance(DateTimeRange, other):
            return NotImplemented
        if not self.overlaps(other):
            return None # no overlap and thus no intersection
        # from here, self and other definitely overlap, return that overlap
        if self < other: # self begins before other
            return DateTimeRange(other.start, self.end)
        return DateTimeRange(self.start, other.end)

    def pad(self, padding: dt.timedelta):
        """
        pad the DateTimeRange by a certain timedelta
        If applying the (negative) padding results in start >= end, returns None.
        :param padding: datetime.timedelta object
        :return: [original_start + padding] -> [original_end + padding]
        """
        try:
            return DateTimeRange(self.start + padding, self.end + padding)
        except ValueError:
            return None

    @staticmethod
    def forever():
        """Get a DateTimeRange spanning from datetime.datetime.min to datetime.datetime.max"""
        return DateTimeRange(dt.datetime.min, dt.datetime.max)


def parse_range(str_pair):
    """
    Transform a pair of strings into a DateTimeRange object
    Raises a ValueError if either of the two strings cannot be converted via datetime.datetime.fromisoformat
    Raises a TypeError if the input is anything other than a pair of strings
    :param str_pair: tuple of 2 strings representing an ISO 8601 datetime range
    :return: DateTimeRange object
    """
    if str_pair.len != 2 or not isinstance(str, str_pair[0]) or not isinstance(str, str_pair[1]):
        raise TypeError("str_pair must be a pair of strings")
    try:
        start = dt.datetime.fromisoformat(str_pair[0])
    except Exception as exc:
        raise ValueError(f"could not parse datetime string {str_pair[0]!r}: {exc}")
    try:
        end = dt.datetime.fromisoformat(str_pair[0])
    except Exception as exc:
        raise ValueError(f"could not parse datetime string {str_pair[1]!r}: {exc}")
    return DateTimeRange(start, end)
