"""
The schedule audit (docs/explanation/schedule-audit.md): a finished schedule judged the way its workers would, each
compared with the others. A development tool, independent of tinyscheg.csp and tinyscheg.scoring.
Usage: PYTHONPATH=src python tools/audit.py INPUT SCHEDULE
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import math
import pathlib
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace

from schedule_checker import hard_constraint_violations
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.model.shift_generation import all_slots, generate_shifts
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.schedule_reader import ScheduleReadError, read_schedule
from tinyscheg.parsing.validation import InputError
from tinyscheg.timing.datetime_range import DateTimeRange

TOLERANCE = 1                               # a gap of one (shift, short straw, ...) is tolerated; more is a complaint
DAY_LENGTH = dt.timedelta(hours=24)         # load is also compared over every stretch this long within the period
                                            # ("during the day"), wherever it starts: midnight means nothing special
SHORT_REST_MARGIN = dt.timedelta(hours=2)   # a rest shorter than the schedule's typical rest by more than this is a
                                            # short straw: each schedule is judged by the norms it sets itself
MAX_CHANGES = 3                             # an easy fix is a chain of at most this many moves and swaps
SEVERITY_EPSILON = 1e-9                     # severities closer than this are equal (hours are divided as floats)
SHOWN_DECIMALS = 2                          # decimals shown for hours and severities
EPSILON = 1e-9                              # hours (and fractions of a shift or a pairing) closer than this are equal:
                                            # they're computed as floats
DEFAULT_MAX_CHANGES = 3                     # how far the fix search reaches by default (ADR 0048): "no fix" means none
                                            # of up to this many moves and swaps

WHOLE_PERIOD = "overall"                    # the label of the window covering the whole period
ANY_DAY = f"in any {DAY_LENGTH / dt.timedelta(hours=1):g} hours"  # the label of load complaints over day windows

LOAD = "load"
SHORT_STRAWS = "short straws"
LIKED_PARTNERS = "liked partners"
# complaints listed on the cards and reported apart, but left out of the summary's main measures (decided 2026-11-11;
# see docs/explanation/schedule-audit.md#liked-partner-complaints-are-counted-apart): the likes penalty can't weigh
# how evenly liked pairings are spread, and it isn't clear workers hold that against a schedule
SEPARATE_KINDS = (LIKED_PARTNERS,)

SHORT_REST = "short rest"
DISLIKED_PARTNER = "disliked partner"
REST = "rest"                               # the kinds of grievance (ADR 0048, ADR 0049): LOAD, REST, DISLIKED_PARTNER,
MISSING_LIKE = "missing like"               # MISSING_LIKE
LARGER_REST = "larger rest event"           # what a fix creates when it makes a worker's rest event larger
NO_PERSON = -1                              # the person of a grievance that isn't about one (load, rest)
STRAW_KINDS = (SHORT_REST, DISLIKED_PARTNER)  # a day's load isn't a straw: load complaints already measure it

EXIT_SUCCESS = 0
EXIT_ILLEGAL = 1  # the schedule breaks a hard constraint, so there's nothing to audit
EXIT_USAGE = 2    # invalid arguments, or the files couldn't be read or don't match


# --- the fixed part: windows and availability ---

@dataclass(frozen=True, slots=True)
class Window:
    """A stretch of time load is compared over: a day window (DAY_LENGTH long), or the whole period."""
    label: str
    time: DateTimeRange


@dataclass(frozen=True, slots=True)
class AuditContext:
    """
    Everything about an input that doesn't depend on the assignment, computed once.
    windows are the day windows, then the whole period; shift_windows[s] the labels of the windows shift s overlaps,
    and shift_overlap[s] how many of its hours fall in each of them, in the same order. availability[w][label] is
    worker w's available hours in that window; occupied holds the labels of the windows any shift overlaps. With a
    history, the shifts and slots are the whole schedule's, the history's first: fixed_slots is how many slots it has,
    which no easy fix may change.
    """
    schedule_input: ScheduleInput
    shifts: tuple[Shift, ...]
    slots: tuple[Slot, ...]
    windows: tuple[Window, ...]
    shift_windows: tuple[tuple[str, ...], ...]
    shift_overlap: tuple[tuple[float, ...], ...]
    availability: tuple[dict[str, float], ...]
    occupied: frozenset[str]
    likes: tuple[frozenset[int], ...]
    dislikes: tuple[frozenset[int], ...]
    fixed_slots: int = 0
    staffed_availability: tuple[float, ...] = ()           # per worker: hours available while a post is staffed
    away: tuple[tuple[DateTimeRange, ...], ...] = ()        # per worker: when they could neither work nor rest


def hours(length: dt.timedelta) -> float:
    """A datetime.timedelta in hours."""
    return length / dt.timedelta(hours=1)


def merged(ranges: Iterable[DateTimeRange]) -> list[DateTimeRange]:
    """Ranges joined where they overlap or touch, in time order."""
    result: list[DateTimeRange] = []
    for time in sorted(ranges):
        if result and time.start <= result[-1].end:
            if time.end > result[-1].end:
                result[-1] = DateTimeRange(result[-1].start, time.end)
        else:
            result.append(time)
    return result


def staffed_hours(staffed: Sequence[DateTimeRange], periods: Sequence[tuple[DateTimeRange, Sequence[Worker | None]]],
                  index: int) -> float:
    """
    A worker's availability as the audit counts it (ADR 0048): the hours when at least one post is staffed, in the
    periods whose input they were in, minus their unavailability
    :param staffed: when at least one post is staffed, merged
    :param periods: every period of the whole schedule, each with each worker as they were in its input (None if they
    weren't in it)
    :param index: the worker's index
    :return: the hours
    """
    return math.fsum(available_hours(then[index].unavailable, time, part)
                     for part, then in periods if then[index] is not None for time in staffed)


def away_times(periods: Sequence[tuple[DateTimeRange, Sequence[Worker | None]]],
               index: int) -> tuple[DateTimeRange, ...]:
    """
    When a worker could neither work nor rest, over the whole schedule (ADR 0038): their unavailability in each period
    whose input they were in, every period whose input they weren't in, and the time between periods
    :param periods: every period of the whole schedule, in time order, each with each worker as they were in its input
    :param index: the worker's index
    :return: the times, merged, in time order
    """
    times: list[DateTimeRange] = []
    for part, then in periods:
        if then[index] is None:
            times.append(part)
        else:
            times += [inside for absence in then[index].unavailable
                      if (inside := absence.intersection(part)) is not None]
    times += [DateTimeRange(earlier.end, later.start)
              for (earlier, _), (later, _) in zip(periods, periods[1:]) if earlier.end < later.start]
    return tuple(merged(times))


def available_between(away: Sequence[DateTimeRange], start: dt.datetime, end: dt.datetime) -> float:
    """
    The available part of the time between two moments
    :param away: when the worker could neither work nor rest, merged, as away_times gives it
    :param start: datetime.datetime
    :param end: datetime.datetime, after start
    :return: the hours from start to end, minus the time away within them
    """
    left = end - start
    for absence in away:  # merged, so no time is taken off twice
        if absence.start < end and start < absence.end:
            left -= min(end, absence.end) - max(start, absence.start)
    return hours(left)


def day_windows(period: DateTimeRange, shifts: Sequence[Shift]) -> list[Window]:
    """
    The day windows: stretches of DAY_LENGTH within the period, one starting at each shift's start, one ending at each
    shift's end, and one at each end of the period, so that whatever shifts overlap some stretch of DAY_LENGTH also
    overlap one of them. None if the period is no longer than DAY_LENGTH, since the whole period then already compares
    the day.
    :param period: DateTimeRange
    :param shifts: the shifts
    :return: the windows in time order, each labelled with its start
    """
    if period.duration <= DAY_LENGTH:
        return []
    starts = ({shift.time.start for shift in shifts} | {shift.time.end - DAY_LENGTH for shift in shifts}
              | {period.start, period.end - DAY_LENGTH})
    return [Window(f"{start:%Y-%m-%d %H:%M}", DateTimeRange(start, start + DAY_LENGTH)) for start in sorted(starts)
            if period.start <= start and start + DAY_LENGTH <= period.end]


def available_hours(unavailable: Sequence[DateTimeRange], window: DateTimeRange, period: DateTimeRange) -> float:
    """
    A worker's available time in a window
    :param unavailable: the worker's unavailability, sorted by start
    :param window: DateTimeRange
    :param period: DateTimeRange, the schedule's period
    :return: the hours of the window inside the period, minus the unavailability within them (overlaps counted once)
    """
    inside = window.intersection(period)
    if inside is None:
        return 0.0
    away = dt.timedelta(0)
    covered_until = inside.start
    for absence in unavailable:  # sorted by start, so each absence only adds what's beyond the ones before it
        start, end = max(absence.start, covered_until), min(absence.end, inside.end)
        if start < end:
            away += end - start
            covered_until = end
    return hours(inside.duration - away)


def build_context(schedule_input: ScheduleInput, shifts: Sequence[Shift], slots: Sequence[Slot],
                  periods: Sequence[tuple[DateTimeRange, Sequence[Worker | None]]] = (),
                  fixed_slots: int = 0, staffed: Sequence[DateTimeRange] = ()) -> AuditContext:
    """
    Compute what the audit needs about an input, whatever the assignment
    :param schedule_input: ScheduleInput
    :param shifts: the shifts in stable order
    :param slots: the slots in stable order
    :param periods: with a history, every period of the whole schedule in time order, each with each worker as they
    were in that period's input (None if they weren't in it), for availability; empty for the input's period alone
    :param fixed_slots: with a history, how many of the slots (the first ones) are the history's
    :param staffed: when at least one post is staffed; empty for the times of the shifts given
    :return: the AuditContext
    """
    if not periods:
        periods = [(schedule_input.settings.period, schedule_input.workers)]
    staffed = merged(staffed or (shift.time for shift in shifts))
    period = DateTimeRange(periods[0][0].start, periods[-1][0].end)
    windows = tuple(day_windows(period, shifts)) + (Window(WHOLE_PERIOD, period),)
    overlapping = [[(window.label, hours(inside.duration)) for window in windows
                    if (inside := window.time.intersection(shift.time)) is not None
                    and inside.duration > dt.timedelta(0)]
                   for shift in shifts]
    shift_windows = tuple(tuple(label for label, _ in pairs) for pairs in overlapping)
    shift_overlap = tuple(tuple(overlap for _, overlap in pairs) for pairs in overlapping)
    index_of = {worker.name: index for index, worker in enumerate(schedule_input.workers)}
    return AuditContext(
        schedule_input=schedule_input, shifts=tuple(shifts), slots=tuple(slots), windows=windows,
        shift_windows=shift_windows, shift_overlap=shift_overlap,
        availability=tuple({window.label: sum(available_hours(then[index].unavailable, window.time, part)
                                              for part, then in periods if then[index] is not None)
                            for window in windows} for index in range(len(schedule_input.workers))),
        occupied=frozenset(label for labels in shift_windows for label in labels),
        likes=tuple(frozenset(index_of[name] for name in worker.likes) for worker in schedule_input.workers),
        dislikes=tuple(frozenset(index_of[name] for name in worker.dislikes) for worker in schedule_input.workers),
        fixed_slots=fixed_slots,
        staffed_availability=tuple(staffed_hours(staffed, periods, index)
                                   for index in range(len(schedule_input.workers))),
        away=tuple(away_times(periods, index) for index in range(len(schedule_input.workers))))


def with_history(schedule_input: ScheduleInput, shifts: Sequence[Shift],
                 assignment: Sequence[int]) -> tuple[AuditContext, tuple[int, ...]]:
    """
    The context and assignment of a schedule together with its history, as one schedule (ADR 0031), built here from
    the model alone, independently of tinyscheg.csp: each previous schedule's shifts from its own input, with its
    workers matched by name (slots of workers who have left dropped), then the new period's
    :param schedule_input: ScheduleInput with a history
    :param shifts: the new period's shifts, in stable order
    :param assignment: a worker index per new slot
    :return: (the AuditContext, the whole schedule's assignment)
    """
    index_of = {worker.name: index for index, worker in enumerate(schedule_input.workers)}
    history = sorted(schedule_input.history, key=lambda previous: previous.schedule_input.settings.period.start)
    parts: list[tuple[Shift, list[int]]] = []
    periods: list[tuple[DateTimeRange, list[Worker | None]]] = []
    staffed: list[DateTimeRange] = [shift.time for shift in shifts]
    for previous in history:
        names = [worker.name for worker in previous.schedule_input.workers]
        then = {worker.name: worker for worker in previous.schedule_input.workers}
        periods.append((previous.schedule_input.settings.period,
                        [then.get(worker.name) for worker in schedule_input.workers]))
        for shift in generate_shifts(previous.schedule_input.posts, previous.schedule_input.settings.period):
            staffed.append(shift.time)  # staffed, even if only by workers who have since left
            kept = [slot for slot in shift.slots if names[previous.assignment[slot.index]] in index_of]
            if kept:
                parts.append((replace(shift, slots=tuple(kept)),
                              [index_of[names[previous.assignment[slot.index]]] for slot in kept]))
    fixed_slots = sum(len(workers) for _, workers in parts)
    parts += [(shift, [assignment[slot.index] for slot in shift.slots]) for shift in shifts]
    periods.append((schedule_input.settings.period, list(schedule_input.workers)))
    whole: list[Shift] = []
    next_slot = 0
    for shift_index, (shift, _) in enumerate(parts):
        slots = tuple(replace(slot, index=next_slot + offset, shift_index=shift_index)
                      for offset, slot in enumerate(shift.slots))
        next_slot += len(slots)
        whole.append(replace(shift, index=shift_index, slots=slots))
    whole_assignment = tuple(worker for _, workers in parts for worker in workers)
    return build_context(schedule_input, whole, all_slots(whole), periods, fixed_slots, staffed), whole_assignment


# --- each worker's statistics ---

@dataclass(frozen=True, slots=True)
class WorkerStats:
    """
    One worker's side of a schedule. shift_count, shift_hours (the hours inside the window) and shortest_held (the
    length of the worker's shortest shift overlapping it) are per window label; rests are in hours, in time order;
    partners counts the shifts shared with each other worker; straws counts each kind of short straw.
    """
    shifts: tuple[int, ...]
    shift_count: dict[str, int]
    shift_hours: dict[str, float]
    shortest_held: dict[str, float]
    rests: tuple[float, ...]
    partners: dict[int, int]
    liked_shared: int
    disliked_shared: int
    straws: dict[str, int]

    @property
    def total_straws(self) -> int:
        """All the worker's short straws."""
        return sum(self.straws.values())


def workers_by_shift(context: AuditContext, assignment: Sequence[int]) -> list[tuple[int, ...]]:
    """Each shift's workers, in slot order."""
    return [tuple(assignment[slot.index] for slot in shift.slots) for shift in context.shifts]


def worker_stats(context: AuditContext, assignment: Sequence[int],
                 short_rest: float | None = None) -> tuple[tuple[WorkerStats, ...], float]:
    """
    Every worker's statistics
    :param context: AuditContext
    :param assignment: a worker index per slot
    :param short_rest: a rest shorter than this many hours is a short straw; None for the schedule's own norm, its
    typical rest less SHORT_REST_MARGIN
    :return: (a WorkerStats per worker, in input order; the short-rest threshold used)
    """
    crews = workers_by_shift(context, assignment)
    workers = range(len(context.schedule_input.workers))
    own = [tuple(index for index, crew in enumerate(crews) if worker in crew) for worker in workers]  # time order
    rests = [_rests(context, shifts) for shifts in own]
    if short_rest is None:
        short_rest = typical_rest(rests) - hours(SHORT_REST_MARGIN)
    stats = tuple(_one_worker(context, crews, worker, own[worker], rests[worker], short_rest) for worker in workers)
    return stats, short_rest


def _rests(context: AuditContext, own: tuple[int, ...]) -> tuple[float, ...]:
    """The rests, in hours, between a worker's shifts (given by index)."""
    times = sorted(context.shifts[index].time for index in own)
    return tuple(hours(later.start - earlier.end) for earlier, later in zip(times, times[1:]))


def typical_rest(rests: Sequence[Sequence[float]]) -> float:
    """
    The schedule's typical rest, the norm short rests are measured against: the median of every worker's rests
    :param rests: each worker's rests, in hours
    :return: the median rest in hours; infinity if nobody has a rest, so that no rest is short
    """
    every_rest = [rest for worker_rests in rests for rest in worker_rests]
    return statistics.median(every_rest) if every_rest else float("inf")


def _one_worker(context: AuditContext, crews: list[tuple[int, ...]], worker: int, own: tuple[int, ...],
                rests: tuple[float, ...], short_rest: float) -> WorkerStats:
    """
    The statistics of one worker
    :param context: AuditContext
    :param crews: every shift's workers
    :param worker: the worker's index
    :param own: the worker's shifts, by index, in time order
    :param rests: the worker's rests, in hours
    :param short_rest: a rest shorter than this many hours is a short straw
    :return: WorkerStats
    """
    count: Counter[str] = Counter()
    worked: Counter[str] = Counter()
    shortest: dict[str, float] = {}
    for index in own:  # a shift counts in every window it overlaps, with the hours that fall in it
        length = hours(context.shifts[index].time.duration)
        for label, overlap in zip(context.shift_windows[index], context.shift_overlap[index]):
            count[label] += 1
            worked[label] += overlap
            shortest[label] = min(shortest.get(label, length), length)
    partners: Counter[int] = Counter(other for index in own for other in set(crews[index]) if other != worker)
    liked = sum(1 for index in own if context.likes[worker] & set(crews[index]))
    disliked = sum(1 for index in own if context.dislikes[worker] & set(crews[index]))
    straws = {SHORT_REST: sum(1 for rest in rests if rest < short_rest), DISLIKED_PARTNER: disliked}
    return WorkerStats(own, dict(count), dict(worked), shortest, rests, dict(partners), liked, disliked, straws)


# --- complaints ---

@dataclass(frozen=True, slots=True)
class Complaint:
    """A complaint by one worker against another about one measure over one window; gap is how far apart they are."""
    kind: str
    worker: int
    against: int
    window: str
    gap: float

    @property
    def severity(self) -> float:
        """How far the gap goes past the tolerance."""
        return self.gap - TOLERANCE

    @property
    def key(self) -> tuple[str, int, int, str]:
        """What identifies the complaint, whatever its severity."""
        return self.kind, self.worker, self.against, self.window


@dataclass(frozen=True, slots=True)
class Audit:
    """
    A schedule's audit: every worker's statistics and every complaint, most severe first, and the short-rest
    threshold the straws were counted with
    """
    stats: tuple[WorkerStats, ...]
    complaints: tuple[Complaint, ...]
    short_rest: float = float("inf")


def is_peer(context: AuditContext, worker: int, other: int, label: str) -> bool:
    """True if the other worker was available at least as long as the worker in the window, and for some time."""
    other_hours = context.availability[other][label]
    return other != worker and other_hours > 0 and other_hours >= context.availability[worker][label]


def evaluate(context: AuditContext, assignment: Sequence[int], short_rest: float | None = None) -> Audit:
    """
    Audit a schedule
    :param context: AuditContext
    :param assignment: a worker index per slot
    :param short_rest: the short-rest threshold in hours, to judge a changed schedule by the norm of the schedule it
    was changed from; None for the schedule's own norm
    :return: the Audit
    """
    stats, short_rest = worker_stats(context, assignment, short_rest)
    complaints = _load_complaints(context, stats) + _straw_complaints(context, stats) + _liked_complaints(context,
                                                                                                         stats)
    return Audit(stats, tuple(sorted(complaints, key=lambda c: (-c.severity, c.worker, c.kind, c.window, c.against))),
                 short_rest)


def _pairs(context: AuditContext, label: str) -> Iterator[tuple[int, int]]:
    """Every (worker, peer) pair for a window."""
    for worker, other in itertools.permutations(range(len(context.schedule_input.workers)), 2):
        if is_peer(context, worker, other, label):
            yield worker, other


def load_gap(context: AuditContext, stats: tuple[WorkerStats, ...], worker: int, other: int, label: str) -> float:
    """
    How far a worker's load exceeds another's in a window, if it does by one measure and is no less by the other (no
    exchange rate between shifts and hours is assumed, so more shifts but fewer hours isn't more load): the gap in
    shifts, or in hours over the worker's own shortest shift in the window, whichever is larger. Moving a shift of h
    hours from the worker to the other turns a gap of g hours into g - 2h, narrower only if h < g: so, as a gap of one
    shift, a gap in hours no larger than the worker's shortest shift can't be narrowed by moving one of their shifts.
    :return: the gap; 0 if the other worker did more by either measure
    """
    mine, theirs = stats[worker], stats[other]
    shifts = mine.shift_count.get(label, 0) - theirs.shift_count.get(label, 0)
    worked = mine.shift_hours.get(label, 0.0) - theirs.shift_hours.get(label, 0.0)
    if shifts < 0 or worked < -SEVERITY_EPSILON:
        return 0.0
    hours_gap = worked / mine.shortest_held[label] if worked > SEVERITY_EPSILON else 0.0  # more hours: they have shifts
    return max(shifts, hours_gap)


def worst_day(context: AuditContext, stats: tuple[WorkerStats, ...], worker: int, other: int) -> tuple[str, float]:
    """
    The day window in which a worker's load most exceeds another's, among those in which the other is a peer
    :return: (the window's label, the gap); ("", 0.0) if there's no such window
    """
    worst = ("", 0.0)
    for window in context.windows[:-1]:
        if window.label in context.occupied and is_peer(context, worker, other, window.label):
            gap = load_gap(context, stats, worker, other, window.label)
            if gap > worst[1] + SEVERITY_EPSILON:
                worst = (window.label, gap)
    return worst


def _load_complaints(context: AuditContext, stats: tuple[WorkerStats, ...]) -> list[Complaint]:
    """
    Load complaints, over the whole period, and in any day: one per pair of workers, over the day window where the
    gap is widest, so that overlapping windows don't count the same extra load several times
    """
    result = []
    if WHOLE_PERIOD in context.occupied:
        for worker, other in _pairs(context, WHOLE_PERIOD):
            gap = load_gap(context, stats, worker, other, WHOLE_PERIOD)
            if gap > TOLERANCE + SEVERITY_EPSILON:
                result.append(Complaint(LOAD, worker, other, WHOLE_PERIOD, gap))
    if len(context.windows) > 1:
        for worker, other in itertools.permutations(range(len(context.schedule_input.workers)), 2):
            gap = worst_day(context, stats, worker, other)[1]
            if gap > TOLERANCE + SEVERITY_EPSILON:
                result.append(Complaint(LOAD, worker, other, ANY_DAY, gap))
    return result


def _straw_complaints(context: AuditContext, stats: tuple[WorkerStats, ...]) -> list[Complaint]:
    """Short-straw complaints, over the whole period."""
    return [Complaint(SHORT_STRAWS, worker, other, WHOLE_PERIOD, gap)
            for worker, other in _pairs(context, WHOLE_PERIOD)
            if (gap := stats[worker].total_straws - stats[other].total_straws) > TOLERANCE]


def _liked_complaints(context: AuditContext, stats: tuple[WorkerStats, ...]) -> list[Complaint]:
    """Complaints about getting liked partners less often, between workers who like anyone, over the whole period."""
    return [Complaint(LIKED_PARTNERS, worker, other, WHOLE_PERIOD, gap)
            for worker, other in _pairs(context, WHOLE_PERIOD)
            if context.likes[worker] and context.likes[other]
            and (gap := stats[other].liked_shared - stats[worker].liked_shared) > TOLERANCE]


# --- grievances (ADR 0048, ADR 0049): each worker's events, against the best-off peer ---

@dataclass(frozen=True, slots=True)
class Rest:
    """
    A rest between two of a worker's consecutive shifts (by index): its available part in hours (ADR 0038), the mean
    length of the two shifts, and the rest per hour of them, which rests are compared by (ADR 0036's shape)
    """
    before: int
    after: int
    hours: float
    shift_hours: float

    @property
    def per_hour(self) -> float:
        """The rest per hour of the two shifts around it."""
        return self.hours / self.shift_hours


@dataclass(frozen=True, slots=True)
class WorkerFacts:
    """
    One worker's side of a schedule: their shifts (by index, in time order) and hours, their availability while a post
    is staffed, their rests (in time order), how many shifts they shared with each other worker, and their liked
    pairings (each liked person in each of their shifts)
    """
    shifts: tuple[int, ...]
    hours: float
    availability: float
    rests: tuple[Rest, ...]
    partners: dict[int, int]
    liked_pairings: int


@dataclass(frozen=True, slots=True)
class LoadGrievance:
    """
    A worker's extra shifts against their best-off peer, whose shifts and hours are scaled down to the worker's
    availability: events is how many whole extra shifts that is
    """
    worker: int
    peer: int
    events: int
    peer_shifts: float
    peer_hours: float


@dataclass(frozen=True, slots=True)
class RestEvent:
    """
    One of a worker's rests shorter than their peer's in its place, both sorted shortest first (per hour of the shifts
    around them): shortfall is how many hours longer it would have to be to match the peer's, for shifts this long
    """
    rest: Rest
    peer_rest: Rest
    shortfall: float


@dataclass(frozen=True, slots=True)
class RestGrievance:
    """A worker's rests shorter than their best-off peer's, shortest first."""
    worker: int
    peer: int
    events: tuple[RestEvent, ...]


@dataclass(frozen=True, slots=True)
class DislikeEvent:
    """A person a worker dislikes, in one of the worker's shifts (by index): an event in itself (ADR 0049)."""
    shift: int
    person: int


@dataclass(frozen=True, slots=True)
class MissingLike:
    """
    The pairings with one liked person a worker missed against their peer (ADR 0049): the peer's shifts with that
    person in them (apart from the worker and the peer), scaled down to the worker's number of shifts if the peer did
    more, against the worker's own shifts with them; events is how many whole pairings more that is
    """
    person: int
    events: int
    own: int
    peer_shifts: tuple[int, ...]
    peer_scaled: float


@dataclass(frozen=True, slots=True)
class LikeGrievance:
    """A worker's missing likes against their best-off peer, by liked person."""
    worker: int
    peer: int
    missing: tuple[MissingLike, ...]

    @property
    def events(self) -> int:
        """All the pairings missed."""
        return sum(missing.events for missing in self.missing)


@dataclass(frozen=True, slots=True)
class Grievances:
    """
    A schedule's grievances, each worker's by kind (None, or empty, where they have none), with every worker's facts;
    each tuple is in input order
    """
    facts: tuple[WorkerFacts, ...]
    load: tuple[LoadGrievance | None, ...]
    rest: tuple[RestGrievance | None, ...]
    disliked: tuple[tuple[DislikeEvent, ...], ...]
    liked: tuple[LikeGrievance | None, ...]


def shift_hours(context: AuditContext, shift: int) -> float:
    """A shift's length in hours."""
    return hours(context.shifts[shift].time.duration)


def worker_facts(context: AuditContext, crews: Sequence[tuple[int, ...]], worker: int) -> WorkerFacts:
    """
    One worker's facts
    :param context: AuditContext
    :param crews: every shift's workers
    :param worker: the worker's index
    :return: WorkerFacts
    """
    own = tuple(sorted((shift for shift, crew in enumerate(crews) if worker in crew),
                       key=lambda shift: (context.shifts[shift].time, shift)))
    rests = tuple(Rest(earlier, later,
                       available_between(context.away[worker], context.shifts[earlier].time.end,
                                         context.shifts[later].time.start),
                       (shift_hours(context, earlier) + shift_hours(context, later)) / 2)
                  for earlier, later in zip(own, own[1:]))
    partners = Counter(other for shift in own for other in set(crews[shift]) if other != worker)
    liked = sum(len(context.likes[worker] & (set(crews[shift]) - {worker})) for shift in own)
    return WorkerFacts(own, math.fsum(shift_hours(context, shift) for shift in own),
                       context.staffed_availability[worker], rests, dict(partners), liked)


def load_events(context: AuditContext, facts: Sequence[WorkerFacts], worker: int, peer: int) -> LoadGrievance:
    """
    A worker's load events against one peer available at least as long (ADR 0048): the peer's shifts and hours scaled
    down to the worker's availability; if the worker did more by one measure and no less by the other, each whole
    extra shift is an event, and an excess in hours counts as many of the worker's own shifts, shortest first, as fit
    in it; the larger count
    :param context: AuditContext
    :param facts: every worker's facts
    :param worker: the worker's index
    :param peer: the peer's index
    :return: the LoadGrievance (with 0 events if there's none)
    """
    mine, theirs = facts[worker], facts[peer]
    scale = mine.availability / theirs.availability
    peer_shifts, peer_hours = len(theirs.shifts) * scale, theirs.hours * scale
    extra_shifts, extra_hours = len(mine.shifts) - peer_shifts, mine.hours - peer_hours
    if extra_shifts < -EPSILON or extra_hours < -EPSILON:
        return LoadGrievance(worker, peer, 0, peer_shifts, peer_hours)
    by_hours, counted = 0, 0.0
    for length in sorted(shift_hours(context, shift) for shift in mine.shifts):
        counted += length
        if counted > extra_hours + EPSILON:
            break
        by_hours += 1
    events = max(math.floor(extra_shifts + EPSILON), by_hours)
    return LoadGrievance(worker, peer, events, peer_shifts, peer_hours)


def load_grievance(context: AuditContext, facts: Sequence[WorkerFacts], worker: int) -> LoadGrievance | None:
    """
    A worker's load grievance: against the best-off peer among those available at least as long (and for some time),
    the one giving the most events (the first in input order of equals)
    :return: the LoadGrievance, or None if the worker has no load event
    """
    best: LoadGrievance | None = None
    own_availability = facts[worker].availability
    for peer, theirs in enumerate(facts):
        if peer == worker or theirs.availability <= 0 or theirs.availability + EPSILON < own_availability:
            continue
        grievance = load_events(context, facts, worker, peer)
        if grievance.events and (best is None or grievance.events > best.events):
            best = grievance
    return best


def rest_events(mine: Sequence[Rest], theirs: Sequence[Rest]) -> tuple[RestEvent, ...]:
    """
    A worker's rest events against one peer (ADR 0048): both sides' rests sorted shortest first, per hour of the
    shifts around them, and compared in the same places, up to the smaller number of rests
    :param mine: the worker's rests
    :param theirs: the peer's rests
    :return: the events, shortest rest first
    """
    def shortest_first(rests: Sequence[Rest]) -> list[Rest]:
        return sorted(rests, key=lambda rest: (rest.per_hour, rest.before))

    return tuple(RestEvent(own, other, (other.per_hour - own.per_hour) * own.shift_hours)
                 for own, other in zip(shortest_first(mine), shortest_first(theirs))
                 if own.per_hour < other.per_hour - EPSILON)


def rest_grievance(facts: Sequence[WorkerFacts], worker: int) -> RestGrievance | None:
    """
    A worker's rest grievance, against the best-off peer (every worker is a peer): the one giving the most events,
    then the largest shortfalls (the strongest case), then the first in input order
    :return: the RestGrievance, or None if the worker has no rest event
    """
    best: RestGrievance | None = None
    best_case: tuple[int, list[float]] = (0, [])
    for peer, theirs in enumerate(facts):
        if peer == worker:
            continue
        events = rest_events(facts[worker].rests, theirs.rests)
        case = (len(events), sorted((event.shortfall for event in events), reverse=True))
        if events and case > best_case:
            best, best_case = RestGrievance(worker, peer, events), case
    return best


def disliked_events(context: AuditContext, crews: Sequence[tuple[int, ...]],
                    facts: Sequence[WorkerFacts], worker: int) -> tuple[DislikeEvent, ...]:
    """Each person a worker dislikes in each of their shifts, in time order (ADR 0049)."""
    return tuple(DislikeEvent(shift, other) for shift in facts[worker].shifts
                 for other in sorted(set(crews[shift]) & context.dislikes[worker]))


def missing_likes(context: AuditContext, crews: Sequence[tuple[int, ...]], facts: Sequence[WorkerFacts],
                  worker: int, peer: int) -> LikeGrievance:
    """
    A worker's missing likes against one peer (ADR 0049), judged by the worker's own likes applied to the peer's
    shifts: for each liked person, the peer's shifts with them (apart from both), scaled down to the worker's number
    of shifts if the peer did more, never up, against the worker's own; each whole pairing more is an event
    :return: the LikeGrievance (with no events if there's none)
    """
    own_shifts, peer_shifts = facts[worker].shifts, facts[peer].shifts
    scale = min(1.0, len(own_shifts) / len(peer_shifts)) if peer_shifts else 0.0
    missing = []
    for person in sorted(context.likes[worker] - {worker, peer}):
        theirs = tuple(shift for shift in peer_shifts if person in crews[shift])
        own = sum(1 for shift in own_shifts if person in crews[shift])
        events = math.floor(len(theirs) * scale - own + EPSILON)
        if events > 0:
            missing.append(MissingLike(person, events, own, theirs, len(theirs) * scale))
    return LikeGrievance(worker, peer, tuple(missing))


def like_grievance(context: AuditContext, crews: Sequence[tuple[int, ...]], facts: Sequence[WorkerFacts],
                   worker: int) -> LikeGrievance | None:
    """
    A worker's missing-like grievance, against the best-off peer (every worker can be the peer): the one giving the
    most events, the first in input order of equals
    :return: the LikeGrievance, or None if the worker likes nobody or misses no pairing
    """
    best: LikeGrievance | None = None
    if not context.likes[worker]:
        return None
    for peer in range(len(facts)):
        if peer == worker:
            continue
        grievance = missing_likes(context, crews, facts, worker, peer)
        if grievance.events and (best is None or grievance.events > best.events):
            best = grievance
    return best


def find_grievances(context: AuditContext, assignment: Sequence[int]) -> Grievances:
    """
    Every worker's grievances (ADR 0048, ADR 0049)
    :param context: AuditContext
    :param assignment: a worker index per slot
    :return: the Grievances
    """
    crews = workers_by_shift(context, assignment)
    workers = range(len(context.schedule_input.workers))
    facts = tuple(worker_facts(context, crews, worker) for worker in workers)
    return Grievances(facts=facts,
                      load=tuple(load_grievance(context, facts, worker) for worker in workers),
                      rest=tuple(rest_grievance(facts, worker) for worker in workers),
                      disliked=tuple(disliked_events(context, crews, facts, worker) for worker in workers),
                      liked=tuple(like_grievance(context, crews, facts, worker) for worker in workers))


# --- easy fixes as nearby schedules (ADR 0048) ---

GrievanceKey = tuple[str, int, int]  # (kind, worker, person); the person is NO_PERSON for load and rest


@dataclass(frozen=True, slots=True)
class Standing:
    """
    What fixes are judged on, for one schedule: how many events each grievance has, by GrievanceKey; each worker's
    rest shortfalls, largest first; and each worker's shifts, hours, rests per hour of the shifts around them
    (shortest first) and shifts shared with each other worker
    """
    events: dict[GrievanceKey, int]
    shortfalls: tuple[tuple[float, ...], ...]
    shifts: tuple[int, ...]
    hours: tuple[float, ...]
    rests: tuple[tuple[float, ...], ...]
    partners: tuple[dict[int, int], ...]


def standing(grievances: Grievances) -> Standing:
    """The Standing of a schedule, from its Grievances."""
    events: dict[GrievanceKey, int] = {}
    for worker, load in enumerate(grievances.load):
        if load is not None:
            events[(LOAD, worker, NO_PERSON)] = load.events
    for worker, rest in enumerate(grievances.rest):
        if rest is not None:
            events[(REST, worker, NO_PERSON)] = len(rest.events)
    for worker, disliked in enumerate(grievances.disliked):
        for event in disliked:
            key = (DISLIKED_PARTNER, worker, event.person)
            events[key] = events.get(key, 0) + 1
    for worker, liked in enumerate(grievances.liked):
        for missing in liked.missing if liked is not None else ():
            events[(MISSING_LIKE, worker, missing.person)] = missing.events
    return Standing(
        events=events,
        shortfalls=tuple(tuple(sorted((event.shortfall for event in rest.events), reverse=True)) if rest else ()
                         for rest in grievances.rest),
        shifts=tuple(len(facts.shifts) for facts in grievances.facts),
        hours=tuple(facts.hours for facts in grievances.facts),
        rests=tuple(tuple(sorted(rest.per_hour for rest in facts.rests)) for facts in grievances.facts),
        partners=tuple(facts.partners for facts in grievances.facts))


def better_off(key: GrievanceKey, before: Standing, after: Standing) -> bool:
    """
    True if the worker of a grievance is better off in its kind's own terms (ADR 0048): worse in none of its facts and
    better in at least one, so that making the peer worse off (levelling down) is no fix
    :param key: the grievance
    :param before: the audited schedule's Standing
    :param after: the nearby schedule's Standing
    :return: for load, no more shifts and no more hours, and fewer of one; for rest, the new rests compared with the
    old as with a peer's (shortest first, up to the smaller number), none shorter and at least one longer; for a
    disliked partner, a shift fewer with them; for a missing like, a shift more with them
    """
    kind, worker, person = key
    if kind == LOAD:
        shifts, worked = after.shifts[worker] - before.shifts[worker], after.hours[worker] - before.hours[worker]
        return shifts <= 0 and worked <= EPSILON and (shifts < 0 or worked < -EPSILON)
    if kind == REST:
        places = list(zip(after.rests[worker], before.rests[worker]))
        return (all(new >= old - EPSILON for new, old in places)
                and any(new > old + EPSILON for new, old in places))
    shared_before, shared_after = before.partners[worker].get(person, 0), after.partners[worker].get(person, 0)
    return shared_after < shared_before if kind == DISLIKED_PARTNER else shared_after > shared_before


def created_by(before: Standing, after: Standing) -> tuple[tuple[GrievanceKey, int], ...]:
    """
    What a nearby schedule creates, for anyone: each grievance with more events (how many more), and a LARGER_REST
    for each worker with a rest event larger than the one in its place before, both sorted largest first
    :return: the created grievances, sorted; empty if the nearby schedule is harmless
    """
    created = {key: count - before.events.get(key, 0) for key, count in after.events.items()
               if count > before.events.get(key, 0)}
    for worker, (old, new) in enumerate(zip(before.shortfalls, after.shortfalls)):
        if any(larger > smaller + EPSILON for smaller, larger in zip(old, new)):
            created[(LARGER_REST, worker, NO_PERSON)] = 1
    return tuple(sorted(created.items()))


@dataclass(frozen=True, slots=True)
class Step:
    """One change, a move (one slot) or a swap (two): the slots, the workers they go to, and those they come from."""
    slots: tuple[int, ...]
    workers: tuple[int, ...]
    previous: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NearbyFix:
    """
    A nearby schedule that removes some of a grievance's events with its worker better off: the changes that reach
    it, how many events it removes, and what it creates (harmless if nothing)
    """
    steps: tuple[Step, ...]
    removes: int
    creates: tuple[tuple[GrievanceKey, int], ...]

    @property
    def harmless(self) -> bool:
        """True if the fix creates nothing for anyone."""
        return not self.creates


@dataclass(frozen=True, slots=True)
class FixesFound:
    """A grievance's smallest harmless fix, if one was found, and otherwise the transfers no other one dominates."""
    harmless: NearbyFix | None
    transfers: tuple[NearbyFix, ...]


def includes(larger: Sequence[tuple[GrievanceKey, int]], smaller: Sequence[tuple[GrievanceKey, int]]) -> bool:
    """True if one set of created grievances (with counts) includes another."""
    counts = dict(larger)
    return all(count <= counts.get(key, 0) for key, count in smaller)


def keep_undominated(transfers: list[NearbyFix], transfer: NearbyFix) -> None:
    """
    Add a transfer to a grievance's list unless another creates a subset of what it creates with no more changes, and
    drop those it dominates in turn (a set comparison, not an exchange rate)
    :param transfers: the list, changed in place
    :param transfer: NearbyFix
    """
    if any(includes(transfer.creates, other.creates) and len(other.steps) <= len(transfer.steps)
           for other in transfers):
        return
    transfers[:] = [other for other in transfers
                    if not (includes(other.creates, transfer.creates) and len(transfer.steps) <= len(other.steps))]
    transfers.append(transfer)


@dataclass(frozen=True, slots=True)
class SearchSpace:
    """
    What the fix search needs about an input: the slots fixes may change (the new period's), who may take each slot
    (role and availability), every slot's time and shift, and the minimum rest
    """
    changeable: tuple[int, ...]
    eligible: tuple[tuple[int, ...], ...]
    times: tuple[DateTimeRange, ...]
    shift_of: tuple[int, ...]
    min_rest: dt.timedelta


def search_space(context: AuditContext) -> SearchSpace:
    """The SearchSpace of an input."""
    workers = context.schedule_input.workers
    return SearchSpace(
        changeable=tuple(range(context.fixed_slots, len(context.slots))),
        eligible=tuple(tuple(index for index, worker in enumerate(workers)
                             if worker.has_role(slot.role) and worker.is_available(slot.time))
                       for slot in context.slots),
        times=tuple(slot.time for slot in context.slots),
        shift_of=tuple(slot.shift_index for slot in context.slots),
        min_rest=context.schedule_input.settings.min_rest)


def too_close(space: SearchSpace, first: int, second: int) -> bool:
    """True if one worker can't hold both slots: they overlap, are back to back or are closer than the minimum rest."""
    one, other = space.times[first], space.times[second]
    rest = max(other.start - one.end, one.start - other.end)  # negative if they overlap
    return rest <= dt.timedelta(0) or rest < space.min_rest


Conflict = tuple[int, int]  # two slots one worker holds too close together, the lower index first


def clashes(space: SearchSpace, own: set[int], slot: int, given_away: int | None = None) -> list[Conflict]:
    """The slots a worker holds (but the one they give away) that would be too close to a slot they receive."""
    return [(min(slot, other), max(slot, other)) for other in own
            if other != given_away and too_close(space, slot, other)]


def changes_from(space: SearchSpace, current: Sequence[int], own: Sequence[set[int]],
                 moving: Sequence[int] | None = None) -> Iterator[tuple[Step, list[Conflict]]]:
    """
    Every move and swap from a schedule that gives each slot it changes to a worker with its role and available then,
    with the conflicts it leaves the workers receiving slots with
    :param space: SearchSpace
    :param current: the schedule, a worker per slot
    :param own: each worker's slots in it
    :param moving: if given, only the changes that move one of these slots
    :return: (the Step, its conflicts), moves before swaps, in stable slot and worker order
    """
    slots = space.changeable if moving is None else moving
    for slot in slots:
        holder = current[slot]
        for worker in space.eligible[slot]:
            if worker != holder:
                yield Step((slot,), (worker,), (holder,)), clashes(space, own[worker], slot)
    moving_set = set(slots)
    for first in slots:
        for second in space.changeable:
            if second == first or (second in moving_set and second < first):
                continue  # each pair once
            one, other = current[first], current[second]
            if (one == other or space.shift_of[first] == space.shift_of[second]
                    or other not in space.eligible[first] or one not in space.eligible[second]):
                continue
            low, high = (first, second) if first < second else (second, first)
            yield (Step((low, high), (current[high], current[low]), (current[low], current[high])),
                   clashes(space, own[other], first, second) + clashes(space, own[one], second, first))


def one_change_resolves(conflicts: frozenset[Conflict]) -> bool:
    """True if a single change, moving at most two slots, could resolve every conflict: two slots cover them all."""
    slots = sorted({slot for conflict in conflicts for slot in conflict})
    return any(all(first in conflict or second in conflict for conflict in conflicts)
               for first, second in itertools.combinations_with_replacement(slots, 2))


@dataclass(frozen=True, slots=True)
class _State:
    """A schedule the search reached: how it differs from the audited one, the changes that first reached it, and
    the conflicts it leaves (none if it's legal)."""
    diff: dict[int, int]
    steps: tuple[Step, ...]
    conflicts: frozenset[Conflict]


def nearby_schedules(context: AuditContext, assignment: Sequence[int],
                     max_changes: int) -> Iterator[tuple[tuple[Step, ...], tuple[int, ...]]]:
    """
    Every legal schedule within max_changes moves and swaps of a legal schedule, in the new period only, each once,
    the fewest changes first. Only the nearby schedule must be legal: a change may leave a worker holding two slots too
    close together if the next change resolves it, so that two workers can trade shifts neither could take alone.
    Every slot is always given to a worker with its role and available then.
    :param context: AuditContext
    :param assignment: the audited schedule, a worker per slot
    :param max_changes: how many changes at most
    :return: (the changes that first reached it, the nearby schedule), in breadth-first order
    """
    space = search_space(context)
    workers = len(context.schedule_input.workers)
    seen: set[frozenset[tuple[int, int]]] = {frozenset()}
    level = [_State({}, (), frozenset())]
    for depth in range(1, max_changes + 1):
        next_level: list[_State] = []
        for state in level:
            current = list(assignment)
            for slot, worker in state.diff.items():
                current[slot] = worker
            own: list[set[int]] = [set() for _ in range(workers)]
            for slot, worker in enumerate(current):
                own[worker].add(slot)
            moving = sorted({slot for conflict in state.conflicts for slot in conflict}) if state.conflicts else None
            for step, new_conflicts in changes_from(space, current, own, moving):
                conflicts = frozenset(conflict for conflict in state.conflicts
                                      if conflict[0] not in step.slots and conflict[1] not in step.slots)
                conflicts |= frozenset(new_conflicts)
                if conflicts and (state.conflicts or depth == max_changes or not one_change_resolves(conflicts)):
                    continue  # a conflict must be resolved by the next change, within max_changes
                diff = dict(state.diff)
                for slot, worker in zip(step.slots, step.workers):
                    if worker == assignment[slot]:
                        diff.pop(slot, None)
                    else:
                        diff[slot] = worker
                key = frozenset(diff.items())
                if key in seen:
                    continue
                seen.add(key)
                reached = _State(diff, state.steps + (step,), conflicts)
                if depth < max_changes:
                    next_level.append(reached)
                if not conflicts:
                    nearby = list(current)
                    for slot, worker in zip(step.slots, step.workers):
                        nearby[slot] = worker
                    yield reached.steps, tuple(nearby)
        level = next_level


def search_fixes(context: AuditContext, assignment: Sequence[int], grievances: Grievances,
                 max_changes: int = DEFAULT_MAX_CHANGES) -> dict[GrievanceKey, FixesFound]:
    """
    Search every nearby schedule up to max_changes changes for fixes (ADR 0048), each audited afresh and compared
    with the audited schedule, worker by worker and kind by kind: for each grievance, the smallest harmless fix, or
    else the transfers no other one dominates. Stops once every grievance has a harmless fix, as nothing further
    could be reported.
    :param context: AuditContext
    :param assignment: the audited schedule, which must be legal
    :param grievances: its Grievances
    :param max_changes: how far the search reaches; 0 turns it off
    :return: the fixes found for each grievance with events, by GrievanceKey; empty if max_changes is 0
    """
    before = standing(grievances)
    keys = sorted(key for key, count in before.events.items() if count > 0)
    if max_changes <= 0:
        return {}
    harmless: dict[GrievanceKey, NearbyFix] = {}
    transfers: dict[GrievanceKey, list[NearbyFix]] = {key: [] for key in keys}
    for steps, nearby in nearby_schedules(context, assignment, max_changes) if keys else ():
        if len(harmless) == len(keys):
            break
        after = standing(find_grievances(context, nearby))
        creates = created_by(before, after)
        for key in keys:
            removed = before.events[key] - after.events.get(key, 0)
            if key in harmless or removed <= 0 or not better_off(key, before, after):
                continue
            fix = NearbyFix(steps, removed, creates)
            if fix.harmless:
                harmless[key] = fix
                transfers[key] = [other for other in transfers[key] if len(other.steps) < len(steps)]
            else:
                keep_undominated(transfers[key], fix)
    return {key: FixesFound(harmless.get(key), tuple(transfers[key])) for key in keys}


# --- easy fixes ---

@dataclass(frozen=True, slots=True)
class Change:
    """A simple change to a schedule (a move or a swap), described for the report; changed_slots are the slots it
    gives to a different worker."""
    description: str
    assignment: tuple[int, ...]
    changed_slots: tuple[int, ...]


def describe_shift(shift: Shift) -> str:
    """A shift for the report, e.g. 'front gate 2025-01-01 04:00–08:00'."""
    start, end = shift.time.start, shift.time.end
    end_text = f"{end:%H:%M}" if end.date() == start.date() else f"{end:%Y-%m-%d %H:%M}"
    return f"{shift.post.name} {start:%Y-%m-%d %H:%M}–{end_text}"


def candidate_changes(context: AuditContext, assignment: tuple[int, ...]) -> Iterator[Change]:
    """
    Every move (one slot to another worker), then every swap (two workers exchanging slots in different shifts), in
    stable slot and worker order; legal or not
    """
    names = [worker.name for worker in context.schedule_input.workers]
    changeable = context.slots[context.fixed_slots:]  # the history is what happened: no fix can change it
    for slot in changeable:
        for worker in range(len(names)):
            if worker != assignment[slot.index]:
                changed = list(assignment)
                changed[slot.index] = worker
                yield Change(f"giving {names[worker]} {describe_shift(context.shifts[slot.shift_index])} instead of "
                             f"{names[assignment[slot.index]]}", tuple(changed), (slot.index,))
    for first, second in itertools.combinations(changeable, 2):
        a, b = assignment[first.index], assignment[second.index]
        if a != b and first.shift_index != second.shift_index:
            changed = list(assignment)
            changed[first.index], changed[second.index] = b, a
            yield Change(f"swapping {names[a]}'s {describe_shift(context.shifts[first.shift_index])} with "
                         f"{names[b]}'s {describe_shift(context.shifts[second.shift_index])}", tuple(changed),
                         (first.index, second.index))


def slots_by_worker(assignment: Sequence[int], worker_count: int) -> list[list[int]]:
    """Each worker's slots, in stable order."""
    result: list[list[int]] = [[] for _ in range(worker_count)]
    for slot_index, worker in enumerate(assignment):
        result[worker].append(slot_index)
    return result


def is_legal_change(context: AuditContext, own_slots: list[list[int]], change: Change) -> bool:
    """
    Check a change to a legal schedule for legality, looking only at what it changes: every other worker's shifts
    are as they were, and were legal. Agrees with the full hard-constraint checker (tested), much faster.
    :param context: AuditContext
    :param own_slots: each worker's slots before the change, as slots_by_worker gives them
    :param change: Change
    :return: True if the changed schedule is legal
    """
    workers = context.schedule_input.workers
    receivers = set()
    for slot_index in change.changed_slots:
        slot, worker = context.slots[slot_index], change.assignment[slot_index]
        if not workers[worker].has_role(slot.role) or not workers[worker].is_available(slot.time):
            return False
        receivers.add(worker)
    # giving shifts away can't shorten a rest, so only the workers receiving a slot need their rests checked;
    # a negative rest is an overlap, which includes two slots of the same shift
    min_rest = context.schedule_input.settings.min_rest
    for worker in receivers:
        slot_indexes = [index for index in own_slots[worker] if change.assignment[index] == worker]
        slot_indexes += [index for index in change.changed_slots if change.assignment[index] == worker]
        times = sorted(context.slots[index].time for index in slot_indexes)
        if any(rest <= dt.timedelta(0) or rest < min_rest  # back to back is never legal, even with min_rest 0
               for rest in (later.start - earlier.end for earlier, later in zip(times, times[1:]))):
            return False
    return True


ComplaintKey = tuple[str, int, int, str]


@dataclass(frozen=True, slots=True)
class Baseline:
    """
    What every change is judged against: the audited schedule's complaints (each one's severity, by key), each
    worker's short straws by kind, its short-rest threshold, the norm the schedule set, which no change may move, and
    each worker's rests, shortest first
    """
    severities: dict[ComplaintKey, float]
    straws: tuple[dict[str, int], ...]
    short_rest: float
    rests: tuple[tuple[float, ...], ...] = ()


def baseline(audit: Audit) -> Baseline:
    """The Baseline of an audited schedule."""
    return Baseline({complaint.key: complaint.severity for complaint in audit.complaints},
                    tuple(dict(stats.straws) for stats in audit.stats), audit.short_rest,
                    tuple(tuple(sorted(stats.rests)) for stats in audit.stats))


def is_harmless(before: Baseline, after: Audit) -> bool:
    """
    True if a change creates no new complaint, makes no existing one more severe, gives nobody a short straw of any
    kind they didn't have (a straw happens to a worker, whatever the others have), and makes nobody's short rests
    shorter
    :param before: the Baseline of the audited schedule
    :param after: the Audit after the change, judged by the audited schedule's norm
    """
    return (all(complaint.key in before.severities
                and complaint.severity <= before.severities[complaint.key] + SEVERITY_EPSILON
                for complaint in after.complaints)
            and all(stats.straws[kind] <= straws[kind] for stats, straws in zip(after.stats, before.straws)
                    for kind in straws)
            and all(not _short_rests_shorter(before.rests[worker], stats.rests, before.short_rest)
                    for worker, stats in enumerate(after.stats) if worker < len(before.rests)))


def _short_rests_shorter(before: tuple[float, ...], after: Sequence[float], short_rest: float) -> bool:
    """
    True if a worker's short rests got shorter: comparing their rests shortest first, some short rest after the
    change is shorter than the rest in its place before (or has none in its place). Two rests of 12 hours becoming 7
    and 17 is a shorter short rest, even with the number of short rests the same or smaller (found 2026-11-16).
    :param before: the worker's rests in the audited schedule, shortest first
    :param after: the worker's rests after the change
    :param short_rest: the short-rest threshold, the audited schedule's norm
    :return: True if the change made one of the worker's short rests shorter
    """
    return any(rest < short_rest and (place >= len(before) or rest < before[place])
               for place, rest in enumerate(sorted(after)))


@dataclass(frozen=True, slots=True)
class Fix:
    """An easy fix: a chain of simple changes, each harmless, that together remove a complaint."""
    changes: tuple[Change, ...]

    @property
    def description(self) -> str:
        """The changes in order, e.g. 'giving Bob ... instead of Anne, then swapping ...'."""
        return ", then ".join(change.description for change in self.changes)


@dataclass(frozen=True, slots=True)
class _Step:
    """A harmless change from some schedule, with the audit of the schedule it leads to."""
    change: Change
    audit: Audit

    def severity(self, key: ComplaintKey) -> float:
        """The complaint's severity after the change: 0 if it's gone."""
        return next((c.severity for c in self.audit.complaints if c.key == key), 0.0)

    def removes(self, key: ComplaintKey) -> bool:
        """True if the complaint is gone after the change."""
        return all(c.key != key for c in self.audit.complaints)


def harmless_steps(context: AuditContext, assignment: tuple[int, ...], before: Baseline) -> list[_Step]:
    """
    Every legal move and swap from a schedule that is harmless compared with the audited schedule
    :param context: AuditContext
    :param assignment: the schedule to change, which must be legal
    :param before: the Baseline of the audited schedule
    :return: the harmless steps, in candidate_changes' order
    """
    steps = []
    own_slots = slots_by_worker(assignment, len(context.schedule_input.workers))
    for change in candidate_changes(context, assignment):
        if not is_legal_change(context, own_slots, change):
            continue
        after = evaluate(context, change.assignment, before.short_rest)
        if is_harmless(before, after):
            steps.append(_Step(change, after))
    return steps


def _fix_chain(context: AuditContext, before: Baseline, key: ComplaintKey,
               first_steps: list[_Step]) -> tuple[_Step, ...] | None:
    """
    Look for an easy fix for one complaint, greedily: at each step, take the harmless change that lowers the
    complaint's severity most (the first of equals), until it's gone or MAX_CHANGES changes are made
    :param context: AuditContext
    :param before: the Baseline of the audited schedule
    :param key: the complaint to fix
    :param first_steps: the harmless steps from the audited schedule (shared between complaints)
    :return: the chain of steps, or None if no easy fix was found
    """
    chain: list[_Step] = []
    current, options = before.severities[key], first_steps
    for depth in range(MAX_CHANGES):
        if depth:
            options = harmless_steps(context, chain[-1].change.assignment, before)
        better = [step for step in options if step.severity(key) < current - SEVERITY_EPSILON]
        if not better:
            return None
        best = min(better, key=lambda step: step.severity(key))  # min keeps the first of equals
        chain.append(best)
        if best.removes(key):
            return tuple(chain)
        current = best.severity(key)
    return None


def find_fixes(context: AuditContext, assignment: tuple[int, ...], audit: Audit) -> dict[ComplaintKey, Fix]:
    """
    Find easy fixes (see the spec's Easy fixes section): first single changes, then, for the complaints left, chains
    of up to MAX_CHANGES, most severe complaint first. A chain found for one complaint is also given to every other
    complaint left that it removes.
    :param context: AuditContext
    :param assignment: the audited schedule
    :param audit: its Audit
    :return: the easy fix for each complaint one was found for, by key
    """
    before = baseline(audit)
    if not before.severities:
        return {}
    first_steps = harmless_steps(context, assignment, before)
    fixes: dict[ComplaintKey, Fix] = {}
    for step in first_steps:
        for key in before.severities.keys() - fixes.keys():
            if step.removes(key):
                fixes[key] = Fix((step.change,))
    for complaint in audit.complaints:  # most severe first
        if complaint.key in fixes:
            continue
        chain = _fix_chain(context, before, complaint.key, first_steps)
        if chain is None:
            continue
        fix = Fix(tuple(step.change for step in chain))
        for key in before.severities.keys() - fixes.keys():
            if chain[-1].removes(key):
                fixes[key] = fix
    return fixes


# --- the report ---

@dataclass(frozen=True, slots=True)
class AuditSummary:
    """
    The group summary: how many complaints there are and how many have an easy fix, the severity of those with and
    without one, and severity_by_worker, each worker's total as (worker, severity), most first. All of these leave out
    the SEPARATE_KINDS complaints, which are counted apart: how many, and their severity.
    """
    complaints: int
    easy_fixes: int
    easy_fix_severity: float
    no_fix_severity: float
    aggrieved: int
    concentration: float
    severity_by_worker: tuple[tuple[int, float], ...]
    separate_complaints: int = 0
    separate_severity: float = 0.0


def summarize(audit: Audit, fixes: dict[ComplaintKey, Fix]) -> AuditSummary:
    """
    Summarize an audit for the group
    :param audit: Audit
    :param fixes: the fixes found, by complaint key
    :return: the AuditSummary; concentration is the most aggrieved worker's share of all severity (0 if none)
    """
    main = [complaint for complaint in audit.complaints if complaint.kind not in SEPARATE_KINDS]
    separate = [complaint for complaint in audit.complaints if complaint.kind in SEPARATE_KINDS]
    by_worker: Counter[int] = Counter()
    for complaint in main:
        by_worker[complaint.worker] += complaint.severity
    total = sum(by_worker.values())
    fixable = [complaint for complaint in main if complaint.key in fixes]
    ranked = tuple(sorted(by_worker.items(), key=lambda item: (-item[1], item[0])))
    fixable_severity = sum(complaint.severity for complaint in fixable)
    return AuditSummary(complaints=len(main), easy_fixes=len(fixable), easy_fix_severity=fixable_severity,
                        no_fix_severity=total - fixable_severity,
                        aggrieved=len(by_worker), concentration=ranked[0][1] / total if total else 0.0,
                        severity_by_worker=ranked, separate_complaints=len(separate),
                        separate_severity=sum(complaint.severity for complaint in separate))


def shown(value: float) -> str:
    """A number for the report, with at most SHOWN_DECIMALS decimals."""
    return f"{round(value, SHOWN_DECIMALS):g}"


def describe_complaint(context: AuditContext, audit: Audit, complaint: Complaint) -> str:
    """A complaint in the worker's terms, e.g. 'load on 2025-01-01: 4 shifts (16 h), against Bob's 2 (8 h)'."""
    other = context.schedule_input.workers[complaint.against].name
    mine, theirs = audit.stats[complaint.worker], audit.stats[complaint.against]
    if complaint.kind == LOAD:
        if complaint.window == WHOLE_PERIOD:
            label, when = WHOLE_PERIOD, "overall"
        else:
            label = worst_day(context, audit.stats, complaint.worker, complaint.against)[0]
            when = f"in the {shown(hours(DAY_LENGTH))} hours from {label}"
        return (f"load {when}: {mine.shift_count.get(label, 0)} shifts ({shown(mine.shift_hours.get(label, 0.0))} h), "
                f"against {other}'s {theirs.shift_count.get(label, 0)} ({shown(theirs.shift_hours.get(label, 0.0))} h)")
    if complaint.kind == SHORT_STRAWS:
        return f"short straws: {mine.total_straws}, against {other}'s {theirs.total_straws}"
    return f"shifts with someone they like: {mine.liked_shared}, against {other}'s {theirs.liked_shared}"


def card(context: AuditContext, audit: Audit, fixes: dict[ComplaintKey, Fix], worker: int) -> str:
    """
    One worker's feedback card
    :param context: AuditContext
    :param audit: Audit
    :param fixes: the fixes found, by complaint key
    :param worker: the worker's index
    :return: the card, as lines of text
    """
    workers = context.schedule_input.workers
    stats = audit.stats[worker]
    availability = context.availability[worker]
    lines = [f"{workers[worker].name}: {stats.shift_count.get(WHOLE_PERIOD, 0)} shifts, "
             f"{shown(stats.shift_hours.get(WHOLE_PERIOD, 0.0))} h; available {shown(availability[WHOLE_PERIOD])} h"]
    busiest = max(context.windows[:-1], default=None,
                  key=lambda window: (stats.shift_count.get(window.label, 0), stats.shift_hours.get(window.label, 0)))
    if busiest is not None:
        lines.append(f"  busiest {shown(hours(DAY_LENGTH))} hours, from {busiest.label}: "
                     f"{stats.shift_count.get(busiest.label, 0)} shifts, "
                     f"{shown(stats.shift_hours.get(busiest.label, 0.0))} h; available "
                     f"{shown(availability[busiest.label])} h")
    rests = ", ".join(f"{shown(rest)} h" for rest in stats.rests) or "none"
    lines.append(f"  rests: {rests}")
    straws = ", ".join(f"{kind} {stats.straws[kind]}" for kind in STRAW_KINDS)
    lines.append(f"  short straws: {stats.total_straws} ({straws})")
    partners = ", ".join(f"{workers[other].name} ×{count}" for other, count in sorted(stats.partners.items()))
    lines.append(f"  partners: {partners or 'none'}; with someone they like: {stats.liked_shared}, with someone "
                 f"they dislike: {stats.disliked_shared}")
    own = [complaint for complaint in audit.complaints if complaint.worker == worker]
    lines.append("  complaints:" if own else "  complaints: none")
    for complaint in own:
        fix = fixes.get(complaint.key)
        verdict = f"easy fix: {fix.description}" if fix else "no easy fix found"
        lines.append(f"    - [{shown(complaint.severity)}] {describe_complaint(context, audit, complaint)}; {verdict}")
    return "\n".join(lines)


def describe_summary(context: AuditContext, summary: AuditSummary) -> str:
    """The group summary as lines of text."""
    names = [worker.name for worker in context.schedule_input.workers]
    ranking = ", ".join(f"{names[worker]} {shown(severity)}" for worker, severity in summary.severity_by_worker)
    return "\n".join([
        f"complaints: {summary.complaints} ({summary.easy_fixes} with an easy fix)",
        f"severity: with an easy fix {shown(summary.easy_fix_severity)}, no easy fix found "
        f"{shown(summary.no_fix_severity)}",
        f"workers with complaints: {summary.aggrieved} of {len(names)}",
        f"concentration: {shown(summary.concentration)}" + (f" ({ranking})" if ranking else ""),
        f"left out of the above: {', '.join(SEPARATE_KINDS)}, {summary.separate_complaints} complaints, severity "
        f"{shown(summary.separate_severity)}",
    ])


# --- command line ---

def audit_schedule(schedule_input: ScheduleInput, schedule_path: pathlib.Path) -> str:
    """
    Audit a written schedule; with a history, together with it, as one schedule whose history no fix may change
    :param schedule_input: ScheduleInput the schedule was made for
    :param schedule_path: pathlib.Path of the schedule file (CSV, XLSX or ODS)
    :return: the report: a card per worker, then the group summary
    :raises ScheduleReadError: if the file doesn't match the input
    :raises ValueError: if the schedule breaks a hard constraint
    """
    read = read_schedule(schedule_path, schedule_input)
    violations = hard_constraint_violations(schedule_input, read.slots, read.assignment)
    if violations:
        raise ValueError("the schedule breaks hard constraints:\n" + "\n".join(f"  - {v}" for v in violations))
    if schedule_input.history:
        context, assignment = with_history(schedule_input, read.shifts, read.assignment)
    else:
        context, assignment = build_context(schedule_input, read.shifts, read.slots), read.assignment
    audit = evaluate(context, assignment)
    fixes = find_fixes(context, assignment, audit)
    cards = [card(context, audit, fixes, worker) for worker in range(len(schedule_input.workers))]
    report = cards + [describe_summary(context, summarize(audit, fixes))]
    if schedule_input.history:
        report.insert(0, f"together with its history: {len(schedule_input.history)} previous schedule(s), "
                         f"{context.fixed_slots} slots that no fix may change")
    return "\n\n".join(report)


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the audit from the command line
    :param argv: the arguments, without the program name; None means sys.argv[1:]
    :return: the exit code
    """
    parser = argparse.ArgumentParser(prog="audit", description="Audit a schedule from each worker's point of view.")
    parser.add_argument("input", help="the YAML input file")
    parser.add_argument("schedule", help="the schedule written for it (CSV, XLSX or ODS)")
    arguments = parser.parse_args(argv)
    try:
        print(audit_schedule(read_input(arguments.input), pathlib.Path(arguments.schedule)))
    except (InputError, ScheduleReadError) as exc:
        print(f"audit: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print(f"audit: can't read {exc.filename}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:
        print(f"audit: {exc}", file=sys.stderr)
        return EXIT_ILLEGAL
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
