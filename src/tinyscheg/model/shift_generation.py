"""
Generating a schedule's shifts and slots from its posts, by segments (ADR 0018).
A post's active time is split at every boundary: the schedule's start and end, the edges of the post's daily window and
the edges of its variations. Each piece (segment) follows one set of rules, and its shifts are laid back to back from
the segment's start, the last one cut off at the segment's end.
"""
from __future__ import annotations

from collections.abc import Sequence

from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.timing.datetime_range import DateTimeRange


def active_ranges(post: Post, period: DateTimeRange) -> list[DateTimeRange]:
    """
    Find when a post is active during a period
    :param post: Post
    :param period: DateTimeRange, the schedule's period
    :return: the whole period if the post has no daily window, otherwise each occurrence of its window in the period
    """
    if post.window is None:
        return [period]
    return post.window.occurrences(period)


def segments(post: Post, period: DateTimeRange) -> list[tuple[DateTimeRange, ShiftRules]]:
    """
    Split a post's active time into segments, each following a single set of rules
    :param post: Post
    :param period: DateTimeRange, the schedule's period
    :return: (time range, rules) pairs in time order. Where a variation is in effect, its rules apply; elsewhere the
    post's general rules do. Variations only apply while the post is active.
    """
    variation_times = [(occurrence, variation.rules)
                       for variation in post.variations
                       for occurrence in variation.window.occurrences(period)]
    result = []
    for active in active_ranges(post, period):
        result += _split_by_variations(active, variation_times, post.rules)
    return result


def _split_by_variations(active: DateTimeRange, variation_times: list[tuple[DateTimeRange, ShiftRules]],
                         general: ShiftRules) -> list[tuple[DateTimeRange, ShiftRules]]:
    """
    Split one active range of a post at the edges of its variations
    :param active: DateTimeRange, a range during which the post is active
    :param variation_times: (occurrence, rules) pairs of every variation occurrence in the period; they don't overlap
    :param general: ShiftRules, the post's general rules, for the parts no variation covers
    :return: (time range, rules) pairs covering the active range, in time order
    """
    covered = sorted(((overlap, rules)
                      for occurrence, rules in variation_times
                      if (overlap := occurrence.intersection(active)) is not None),
                     key=lambda pair: pair[0])
    result = []
    position = active.start
    for overlap, rules in covered:
        if position < overlap.start:  # a gap before this variation follows the general rules
            result.append((DateTimeRange(position, overlap.start), general))
        result.append((overlap, rules))
        position = overlap.end
    if position < active.end:
        result.append((DateTimeRange(position, active.end), general))
    return result


def shift_times(segment: DateTimeRange, rules: ShiftRules) -> list[DateTimeRange]:
    """
    Lay shifts back to back across a segment
    :param segment: DateTimeRange
    :param rules: ShiftRules, whose length is the shifts' length
    :return: the shifts' time ranges from the segment's start; the last one is cut off at the segment's end
    """
    times = []
    start = segment.start
    while start < segment.end:
        end = min(start + rules.length, segment.end)
        times.append(DateTimeRange(start, end))
        start = end
    return times


def generate_shifts(posts: Sequence[Post], period: DateTimeRange) -> tuple[Shift, ...]:
    """
    Generate every shift of a schedule, with its slots
    :param posts: the posts, in input order
    :param period: DateTimeRange, the schedule's period
    :return: the shifts in stable order: by (start, end, post's input position). Each shift has one slot per required
    worker, in role order, and slots are numbered in the same order across all shifts. Segments needing no workers
    (a variation with no roles) produce no shifts: the post is closed there.
    """
    planned = []  # (start, end, post position, post, time, rules), sortable into the stable order
    for post_position, post in enumerate(posts):
        for segment, rules in segments(post, period):
            if rules.workers_needed == 0:
                continue
            for time in shift_times(segment, rules):
                planned.append((time.start, time.end, post_position, post, time, rules))
    planned.sort(key=lambda entry: entry[:3])

    shifts = []
    slot_index = 0
    for shift_index, (_, _, _, post, time, rules) in enumerate(planned):
        slots = []
        for role, count in rules.roles:
            for _ in range(count):
                slots.append(Slot(slot_index, shift_index, post, time, role))
                slot_index += 1
        shifts.append(Shift(shift_index, post, time, tuple(slots)))
    return tuple(shifts)


def all_slots(shifts: Sequence[Shift]) -> tuple[Slot, ...]:
    """
    Collect the slots of every shift
    :param shifts: shifts in stable order, as generate_shifts returns them
    :return: every slot, in stable order (slot.index is its position in the result)
    """
    return tuple(slot for shift in shifts for slot in shift.slots)
