"""
The schedule audit (docs/explanation/schedule-audit.md): a finished schedule judged the way its workers would, each
compared with the others, as a list of grievance events per worker and the easy fixes for them (ADR 0048, ADR 0049,
ADR 0050, ADR 0051). A development tool, independent of tinyscheg.csp and tinyscheg.scoring.
Usage: PYTHONPATH=src python tools/audit.py INPUT SCHEDULE [--max-changes K] [--json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import math
import pathlib
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from typing import Any
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

SHOWN_DECIMALS = 2                          # decimals shown for hours and fractions in the report
EPSILON = 1e-9                              # hours (and fractions of a shift or a pairing) closer than this are equal:
                                            # they're computed as floats
DEFAULT_MAX_CHANGES = 3                     # how far the fix search reaches by default (ADR 0048): "no fix" means none
                                            # of up to this many moves and swaps
LOAD_EVENT_SHARE = 0.5                      # a shift of the worker's counts as a load event when at least this share
                                            # of it falls within their extra hours: rounding to the nearest shift
                                            # (ADR 0053)

LOAD = "load"                               # the kinds of grievance (ADRs 0048, 0049, 0051, 0053): LOAD, REST,
REST = "rest"                               # DISLIKED_PARTNER, MISSING_LIKE
DISLIKED_PARTNER = "disliked partner"
MISSING_LIKE = "missing like"
LARGER_REST = "larger rest event"           # what a fix creates when it makes a worker's rest event larger
LONGER_REST = "longer rest"                 # a note, not a grievance (ADR 0055): a worker with no rest event whose
                                            # shortest rest, at the typical rest, could have been longer at no one's
                                            # expense
NO_PERSON = -1                              # the person of a grievance that isn't about one (all but disliked
                                            # partners)

JSON_INDENT = 2                             # the indentation of the JSON report

EXIT_SUCCESS = 0
EXIT_ILLEGAL = 1  # the schedule breaks a hard constraint, so there's nothing to audit
EXIT_USAGE = 2    # invalid arguments, or the files couldn't be read or don't match


# --- the fixed part: availability and time away ---

@dataclass(frozen=True, slots=True)
class AuditContext:
    """
    Everything about an input that doesn't depend on the assignment, computed once. With a history, the shifts and
    slots are the whole schedule's, the history's first: fixed_slots is how many slots it has, which no easy fix may
    change.
    """
    schedule_input: ScheduleInput
    shifts: tuple[Shift, ...]
    slots: tuple[Slot, ...]
    likes: tuple[frozenset[int], ...]               # per worker: the likes that count, not those for someone who
                                                    # dislikes them (ADR 0051)
    dislikes: tuple[frozenset[int], ...]
    staffed_availability: tuple[float, ...]          # per worker: hours available while a post is staffed
    away: tuple[tuple[DateTimeRange, ...], ...]       # per worker: when they could neither work nor rest
    staffed_total: float                              # the hours when at least one post is staffed
    fixed_slots: int = 0


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
    were in that period's input (None if they weren't in it), for availability and time away; empty for the
    input's period alone
    :param fixed_slots: with a history, how many of the slots (the first ones) are the history's
    :param staffed: when at least one post is staffed; empty for the times of the shifts given
    :return: the AuditContext
    """
    if not periods:
        periods = [(schedule_input.settings.period, schedule_input.workers)]
    staffed = merged(staffed or (shift.time for shift in shifts))
    index_of = {worker.name: index for index, worker in enumerate(schedule_input.workers)}
    dislikes = tuple(frozenset(index_of[name] for name in worker.dislikes) for worker in schedule_input.workers)
    return AuditContext(
        schedule_input=schedule_input, shifts=tuple(shifts), slots=tuple(slots),
        likes=tuple(frozenset(index_of[name] for name in worker.likes if index not in dislikes[index_of[name]])
                    for index, worker in enumerate(schedule_input.workers)),
        dislikes=dislikes,
        staffed_availability=tuple(staffed_hours(staffed, periods, index)
                                   for index in range(len(schedule_input.workers))),
        away=tuple(away_times(periods, index) for index in range(len(schedule_input.workers))),
        staffed_total=math.fsum(hours(time.duration) for time in staffed),
        fixed_slots=fixed_slots)


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


def workers_by_shift(context: AuditContext, assignment: Sequence[int]) -> list[tuple[int, ...]]:
    """Each shift's workers, in slot order."""
    return [tuple(assignment[slot.index] for slot in shift.slots) for shift in context.shifts]


# --- grievances (ADR 0048, ADR 0049, ADR 0051, ADR 0053): each worker's events ---

@dataclass(frozen=True, slots=True)
class Rest:
    """
    A rest between two of a worker's consecutive shifts (by index): its available part in hours (ADR 0038), the length
    of the shift before it, and the rest per hour of that shift, which rests are compared by (ADR 0051)
    """
    before: int
    after: int
    hours: float
    shift_hours: float

    @property
    def per_hour(self) -> float:
        """The rest per hour of the shift before it."""
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
    A worker's hours above their share, the schedule's hours split in proportion to availability (ADR 0053): events
    is how many of the worker's own shifts, shortest first, count within the extra hours, each counting when at least
    LOAD_EVENT_SHARE of it falls within what's left of them
    """
    worker: int
    events: int
    extra_hours: float
    share: float


@dataclass(frozen=True, slots=True)
class RestEvent:
    """
    One of a worker's rests shorter than the schedule's typical rest, per hour of the shift before it (ADR 0054):
    shortfall is how many hours longer it would have to be to reach the typical rest, after a shift this long
    """
    rest: Rest
    shortfall: float


@dataclass(frozen=True, slots=True)
class RestGrievance:
    """
    A worker's rests shorter than the typical rest, shortest first (per hour of the shift before each): typical is the
    median of every rest in the schedule, per hour of the shift before it (ADR 0054)
    """
    worker: int
    typical: float
    events: tuple[RestEvent, ...]


@dataclass(frozen=True, slots=True)
class DislikeEvent:
    """A person a worker dislikes, in one of the worker's shifts (by index): an event in itself (ADR 0049)."""
    shift: int
    person: int


@dataclass(frozen=True, slots=True)
class LikeGrievance:
    """A worker's shifts (by index, in time order) with partners, none of whom they like: each an event (ADR 0051)."""
    worker: int
    shifts: tuple[int, ...]

    @property
    def events(self) -> int:
        """How many such shifts."""
        return len(self.shifts)


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
                       shift_hours(context, earlier))
                  for earlier, later in zip(own, own[1:]))
    partners = Counter(other for shift in own for other in set(crews[shift]) if other != worker)
    liked = sum(len(context.likes[worker] & (set(crews[shift]) - {worker})) for shift in own)
    return WorkerFacts(own, math.fsum(shift_hours(context, shift) for shift in own),
                       context.staffed_availability[worker], rests, dict(partners), liked)


def load_share(facts: Sequence[WorkerFacts], worker: int) -> float:
    """A worker's share of the schedule's hours, in proportion to their availability (ADR 0013, ADR 0053)."""
    total_availability = math.fsum(f.availability for f in facts)
    if total_availability <= 0:
        return 0.0
    return math.fsum(f.hours for f in facts) * facts[worker].availability / total_availability


def load_grievance(context: AuditContext, facts: Sequence[WorkerFacts], worker: int) -> LoadGrievance | None:
    """
    A worker's load grievance (ADR 0053): the hours they worked above their share, and as events, their own shifts,
    shortest first, each counting when at least LOAD_EVENT_SHARE of it falls within what's left of those hours
    :param context: AuditContext
    :param facts: every worker's facts
    :param worker: the worker's index
    :return: the LoadGrievance, or None if the worker has no load event
    """
    share = load_share(facts, worker)
    extra_hours = facts[worker].hours - share
    events, counted = 0, 0.0
    for length in sorted(shift_hours(context, shift) for shift in facts[worker].shifts):
        if extra_hours - counted + EPSILON < length * LOAD_EVENT_SHARE:
            break
        events += 1
        counted += length
    return LoadGrievance(worker, events, extra_hours, share) if events else None


def typical_rest(facts: Sequence[WorkerFacts]) -> float | None:
    """
    The schedule's typical rest (ADR 0054): the median of every worker's rests, each per hour of the shift before it
    (rests before a worker's first shift and after their last aren't rests); None if there are none
    """
    rests = [rest.per_hour for worker_facts in facts for rest in worker_facts.rests]
    return statistics.median(rests) if rests else None


def rest_events(rests: Sequence[Rest], typical: float) -> tuple[RestEvent, ...]:
    """
    A worker's rest events (ADR 0054): their rests shorter than the typical rest, per hour of the shift before each
    :param rests: the worker's rests
    :param typical: the schedule's typical rest, per hour of the shift before it
    :return: the events, shortest rest first (per hour of the shift before it)
    """
    return tuple(RestEvent(rest, (typical - rest.per_hour) * rest.shift_hours)
                 for rest in sorted(rests, key=lambda rest: (rest.per_hour, rest.before))
                 if rest.per_hour < typical - EPSILON)


def rest_grievance(facts: Sequence[WorkerFacts], worker: int, typical: float | None) -> RestGrievance | None:
    """
    A worker's rest grievance: their rests shorter than the schedule's typical rest (ADR 0054)
    :param facts: every worker's facts
    :param worker: the worker's index
    :param typical: the schedule's typical rest (typical_rest), or None if it has no rests
    :return: the RestGrievance, or None if the worker has no rest event
    """
    if typical is None:
        return None
    events = rest_events(facts[worker].rests, typical)
    return RestGrievance(worker, typical, events) if events else None


def disliked_events(context: AuditContext, crews: Sequence[tuple[int, ...]],
                    facts: Sequence[WorkerFacts], worker: int) -> tuple[DislikeEvent, ...]:
    """Each person a worker dislikes in each of their shifts, in time order (ADR 0049)."""
    return tuple(DislikeEvent(shift, other) for shift in facts[worker].shifts
                 for other in sorted(set(crews[shift]) & context.dislikes[worker]))


def like_grievance(context: AuditContext, crews: Sequence[tuple[int, ...]], facts: Sequence[WorkerFacts],
                   worker: int) -> LikeGrievance | None:
    """
    A worker's missing likes (ADR 0051), with no peer: each of their shifts with partners, none of whom they like (the
    likes that count, context.likes); a shift worked alone isn't one
    :return: the LikeGrievance, or None if the worker likes nobody or has no such shift
    """
    likes = context.likes[worker]
    if not likes:
        return None

    def with_nobody_liked(shift: int) -> bool:
        partners = set(crews[shift]) - {worker}
        return bool(partners) and not partners & likes
    shifts = tuple(shift for shift in facts[worker].shifts if with_nobody_liked(shift))
    return LikeGrievance(worker, shifts) if shifts else None


def find_grievances(context: AuditContext, assignment: Sequence[int], typical: float | None = None) -> Grievances:
    """
    Every worker's grievances (ADR 0048, ADR 0049, ADR 0051, ADR 0053, ADR 0054)
    :param context: AuditContext
    :param assignment: a worker index per slot
    :param typical: the typical rest to judge rests against; by default the schedule's own (typical_rest). The fix
    search passes the audited schedule's, so that a nearby schedule is judged on the same scale (ADR 0055)
    :return: the Grievances
    """
    crews = workers_by_shift(context, assignment)
    workers = range(len(context.schedule_input.workers))
    facts = tuple(worker_facts(context, crews, worker) for worker in workers)
    typical = typical_rest(facts) if typical is None else typical
    return Grievances(facts=facts,
                      load=tuple(load_grievance(context, facts, worker) for worker in workers),
                      rest=tuple(rest_grievance(facts, worker, typical) for worker in workers),
                      disliked=tuple(disliked_events(context, crews, facts, worker) for worker in workers),
                      liked=tuple(like_grievance(context, crews, facts, worker) for worker in workers))


# --- easy fixes as nearby schedules (ADR 0048) ---

GrievanceKey = tuple[str, int, int]  # (kind, worker, person); the person is NO_PERSON but for disliked partners


@dataclass(frozen=True, slots=True)
class Standing:
    """
    What fixes are judged on, for one schedule: how many events each grievance has, by GrievanceKey; each worker's
    rest shortfalls, largest first; and each worker's hours, rests per hour of the shift before each (shortest first)
    and shifts shared with each other worker
    """
    events: dict[GrievanceKey, int]
    shortfalls: tuple[tuple[float, ...], ...]
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
        if liked is not None:
            events[(MISSING_LIKE, worker, NO_PERSON)] = liked.events
    return Standing(
        events=events,
        shortfalls=tuple(tuple(sorted((event.shortfall for event in rest.events), reverse=True)) if rest else ()
                         for rest in grievances.rest),
        hours=tuple(facts.hours for facts in grievances.facts),
        rests=tuple(tuple(sorted(rest.per_hour for rest in facts.rests)) for facts in grievances.facts),
        partners=tuple(facts.partners for facts in grievances.facts))


def better_off(key: GrievanceKey, before: Standing, after: Standing) -> bool:
    """
    True if the worker of a grievance is better off in its kind's own terms (ADR 0048, ADR 0051): worse in none of its
    facts and better in at least one, so that making others worse off (levelling down) is no fix
    :param key: the grievance
    :param before: the audited schedule's Standing
    :param after: the nearby schedule's Standing
    :return: for load, fewer hours; for rest, the new rests compared with the old, place by place (shortest first,
    up to the smaller number), none shorter and at least one longer; for a disliked partner, a shift fewer with them;
    for missing likes, fewer shifts with nobody they like
    """
    kind, worker, person = key
    if kind == LOAD:
        return after.hours[worker] < before.hours[worker] - EPSILON
    if kind == REST:
        places = list(zip(after.rests[worker], before.rests[worker]))
        return (all(new >= old - EPSILON for new, old in places)
                and any(new > old + EPSILON for new, old in places))
    if kind == MISSING_LIKE:
        return after.events.get(key, 0) < before.events.get(key, 0)
    return after.partners[worker].get(person, 0) < before.partners[worker].get(person, 0)


def worse_off(key: GrievanceKey, before: Standing, after: Standing) -> bool:
    """
    True if a worker's own situation in a grievance's kind got worse (ADR 0050), whatever happened to anyone else
    :param key: the grievance (a LARGER_REST counts as rest)
    :param before: the audited schedule's Standing
    :param after: the nearby schedule's Standing
    :return: for load, more hours; for rest, more rests than before, or a rest shorter than the one in its place
    before (both sorted shortest first, per hour of the shift before each); for a disliked partner, more shifts with
    them; for missing likes, more shifts with nobody they like
    """
    kind, worker, person = key
    if kind == LOAD:
        return after.hours[worker] > before.hours[worker] + EPSILON
    if kind in (REST, LARGER_REST):
        old, new = before.rests[worker], after.rests[worker]
        return len(new) > len(old) or any(shorter < place - EPSILON for shorter, place in zip(new, old))
    if kind == MISSING_LIKE:
        return after.events.get(key, 0) > before.events.get(key, 0)
    return after.partners[worker].get(person, 0) > before.partners[worker].get(person, 0)


def created_by(before: Standing, after: Standing) -> tuple[tuple[GrievanceKey, int], ...]:
    """
    What a nearby schedule creates (ADR 0050): for each worker, each grievance with more events (how many more), and
    a LARGER_REST if a rest event of theirs is larger than the one in its place before (both sorted largest first),
    where their own situation in that kind got worse too; a grievance that grows only because someone else is better
    off (the typical rest rising as others rest longer) isn't created by the change
    :return: the created grievances, sorted; empty if the nearby schedule is harmless
    """
    created = {key: count - before.events.get(key, 0) for key, count in after.events.items()
               if count > before.events.get(key, 0)}
    for worker, (old, new) in enumerate(zip(before.shortfalls, after.shortfalls)):
        if any(larger > smaller + EPSILON for smaller, larger in zip(old, new)):
            created[(LARGER_REST, worker, NO_PERSON)] = 1
    return tuple(sorted((key, count) for key, count in created.items() if worse_off(key, before, after)))


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
    Search every nearby schedule up to max_changes changes for fixes (ADR 0048), each audited afresh (its rests
    against the audited schedule's typical rest, ADR 0055) and compared with the audited schedule, worker by worker
    and kind by kind: for each grievance, the smallest harmless fix, or else the transfers no other one dominates; and
    for each worker checked for a longer rest (rest_note_candidates), the smallest nearby schedule that gives them one
    at no one's expense. Stops once each of these has been found, as nothing further could be reported.
    :param context: AuditContext
    :param assignment: the audited schedule, which must be legal
    :param grievances: its Grievances
    :param max_changes: how far the search reaches; 0 turns it off
    :return: the fixes found for each grievance with events, by GrievanceKey; empty if max_changes is 0
    """
    before = standing(grievances)
    keys = sorted(key for key, count in before.events.items() if count > 0)
    notes = rest_note_candidates(grievances, before)
    typical = typical_rest(grievances.facts)  # nearby schedules are judged against the audited one's (ADR 0055)
    if max_changes <= 0:
        return {}
    harmless: dict[GrievanceKey, NearbyFix] = {}
    transfers: dict[GrievanceKey, list[NearbyFix]] = {key: [] for key in keys}
    for steps, nearby in nearby_schedules(context, assignment, max_changes) if keys or notes else ():
        if len(harmless) == len(keys) + len(notes):
            break
        after = standing(find_grievances(context, nearby, typical))
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
        if not creates:
            for key in notes:
                if key not in harmless and shortest_rest_longer(key[1], before, after):
                    harmless[key] = NearbyFix(steps, 0, ())
    found = {key: FixesFound(harmless.get(key), tuple(transfers[key])) for key in keys}
    return found | {key: FixesFound(harmless[key], ()) for key in notes if key in harmless}


def rest_note_candidates(grievances: Grievances, before: Standing) -> list[GrievanceKey]:
    """
    The workers checked for a rest that could have been longer (ADR 0055): those with no rest event whose shortest
    rest, per hour of the shift before it, is at the typical rest
    :return: their LONGER_REST keys, in input order
    """
    typical = typical_rest(grievances.facts)
    if typical is None:
        return []
    return [(LONGER_REST, worker, NO_PERSON) for worker, rests in enumerate(before.rests)
            if rests and grievances.rest[worker] is None and rests[0] <= typical + EPSILON]


def shortest_rest_longer(worker: int, before: Standing, after: Standing) -> bool:
    """True if a worker's shortest rest is longer and none of their rests shorter (both per hour of the shift before
    each, sorted shortest first and compared place by place), with no fewer rests."""
    old, new = before.rests[worker], after.rests[worker]
    return (len(new) >= len(old) and new[0] > old[0] + EPSILON
            and all(longer >= place - EPSILON for longer, place in zip(new, old)))


# --- the report (ADR 0048, ADR 0049, ADR 0051) ---

def describe_shift(shift: Shift) -> str:
    """A shift for the report, e.g. 'front gate 2025-01-01 04:00–08:00'."""
    start, end = shift.time.start, shift.time.end
    end_text = f"{end:%H:%M}" if end.date() == start.date() else f"{end:%Y-%m-%d %H:%M}"
    return f"{shift.post.name} {start:%Y-%m-%d %H:%M}–{end_text}"


def shown(value: float) -> str:
    """A number for the report, with at most SHOWN_DECIMALS decimals."""
    return f"{round(value, SHOWN_DECIMALS):g}"


KIND_ORDER = (LOAD, REST, DISLIKED_PARTNER, MISSING_LIKE)  # the order kinds are listed in, never added together
HISTORY_MARK = " (in the history)"                          # after an event no change can reach


@dataclass(frozen=True, slots=True)
class GrievanceReport:
    """
    A schedule's audit: its grievances, the fixes found for each (empty if the search was off), and how far the
    search reached (0 if it was off)
    """
    grievances: Grievances
    fixes: dict[GrievanceKey, FixesFound]
    max_changes: int


def report_grievances(context: AuditContext, assignment: Sequence[int],
                      max_changes: int = DEFAULT_MAX_CHANGES) -> GrievanceReport:
    """
    Audit a schedule: every worker's grievances, and the fixes for them within max_changes changes
    :param context: AuditContext
    :param assignment: a worker index per slot, which must be legal
    :param max_changes: how far the fix search reaches; 0 turns it off
    :return: the GrievanceReport
    """
    grievances = find_grievances(context, assignment)
    return GrievanceReport(grievances, search_fixes(context, assignment, grievances, max_changes), max_changes)


def in_history(context: AuditContext, shift: int) -> bool:
    """True if a shift (by index) is in the history, which no fix may change."""
    return context.shifts[shift].slots[0].index < context.fixed_slots


def plural(count: int | float, word: str, words: str | None = None) -> str:
    """A count with its noun, e.g. '1 shift', '2 shifts'."""
    return f"{shown(count)} {word if count == 1 else (words or word + 's')}"


def describe_step(context: AuditContext, step: Step) -> str:
    """A change for the report, e.g. 'give Bob Anne's gate 2025-01-01 04:00–08:00'."""
    names = [worker.name for worker in context.schedule_input.workers]
    shifts = [describe_shift(context.shifts[context.slots[slot].shift_index]) for slot in step.slots]
    if len(step.slots) == 1:
        return f"give {names[step.workers[0]]} {names[step.previous[0]]}'s {shifts[0]}"
    return f"swap {names[step.previous[0]]}'s {shifts[0]} with {names[step.previous[1]]}'s {shifts[1]}"


def describe_created(context: AuditContext, created: Sequence[tuple[GrievanceKey, int]]) -> str:
    """What a transfer creates, e.g. 'Bob: 1 more load event; Cy: 1 more shift with Dana, whom they dislike'."""
    names = [worker.name for worker in context.schedule_input.workers]
    parts: dict[int, list[str]] = {}
    for (kind, worker, person), count in created:
        if kind == LOAD:
            what = plural(count, "more load event", "more load events")
        elif kind == REST:
            what = plural(count, "more rest", "more rests") + " shorter than the typical rest"
        elif kind == LARGER_REST:
            what = "a rest further short of the typical rest"
        elif kind == DISLIKED_PARTNER:
            what = f"{plural(count, 'more shift')} with {names[person]}, whom they dislike"
        else:
            what = f"{plural(count, 'more shift')} with nobody they like"
        parts.setdefault(worker, []).append(what)
    return "; ".join(f"{names[worker]}: {', '.join(whats)}" for worker, whats in parts.items())


def describe_fixes(context: AuditContext, found: FixesFound | None, max_changes: int,
                   wholly_in_history: bool) -> list[str]:
    """
    The lines about a grievance's fixes: its smallest harmless fix, else its transfers (fewest changes first), else no
    fix within max_changes; for a grievance wholly in the history, that no change can reach it; nothing if the search
    was off
    """
    if wholly_in_history:
        return ["in the history: no change can reach it"]
    if max_changes <= 0 or found is None:
        return []
    if found.harmless is not None:
        fix = found.harmless
        return [f"harmless fix ({plural(len(fix.steps), 'change')}, removes {plural(fix.removes, 'event')}): "
                + "; ".join(describe_step(context, step) for step in fix.steps)]
    if found.transfers:
        lines = ["transfers, each removing events but creating others:"]
        for fix in sorted(found.transfers, key=lambda fix: (len(fix.steps), fix.creates)):
            lines.append(f"  {plural(len(fix.steps), 'change')}, removes {plural(fix.removes, 'event')}: "
                         + "; ".join(describe_step(context, step) for step in fix.steps)
                         + f" -> {describe_created(context, fix.creates)}")
        return lines
    return [f"no fix of up to {plural(max_changes, 'change')}"]


@dataclass(frozen=True, slots=True)
class CardEntry:
    """One grievance on a card: its key, its heading, a line per event, how many events it has and how many of
    them lie wholly in the history."""
    key: GrievanceKey
    heading: str
    event_lines: tuple[str, ...]
    events: int
    in_history: int


def describe_rest(context: AuditContext, crews: Sequence[tuple[int, ...]], worker: int, rest: Rest) -> str:
    """A rest for the report, with the shifts around it and who else was in them."""
    names = [w.name for w in context.schedule_input.workers]

    def shift_with(shift: int) -> str:
        others = [names[other] for other in crews[shift] if other != worker]
        return describe_shift(context.shifts[shift]) + (f" (with {', '.join(others)})" if others else "")
    return f"{shown(rest.hours)} h, between {shift_with(rest.before)} and {shift_with(rest.after)}"


def card_entries(context: AuditContext, crews: Sequence[tuple[int, ...]], grievances: Grievances,
                 worker: int) -> list[CardEntry]:
    """A worker's grievances for their card, kind by kind."""
    names = [w.name for w in context.schedule_input.workers]
    facts = grievances.facts[worker]
    entries = []
    load = grievances.load[worker]
    if load is not None:
        entries.append(CardEntry(
            (LOAD, worker, NO_PERSON),
            f"load: {shown(load.extra_hours)} h more than {names[worker]}'s share of {shown(load.share)} h (the "
            f"schedule's hours in proportion to availability), as much as {plural(load.events, 'shift')} of "
            f"{names[worker]}'s ({shown(facts.hours)} h in {plural(len(facts.shifts), 'shift')})",
            (), load.events, 0))
    rest = grievances.rest[worker]
    if rest is not None:
        past = [in_history(context, event.rest.before) and in_history(context, event.rest.after)
                for event in rest.events]
        lines = tuple(f"{describe_rest(context, crews, worker, event.rest)}: {shown(event.shortfall)} h short, after a "
                      f"{shown(event.rest.shift_hours)} h shift ({shown(event.rest.per_hour)} h per hour of it), of "
                      f"the typical {shown(rest.typical * event.rest.shift_hours)} h after a shift this long"
                      + (HISTORY_MARK if wholly_past else "")
                      for event, wholly_past in zip(rest.events, past))
        entries.append(CardEntry((REST, worker, NO_PERSON),
                                 f"rest: {plural(len(rest.events), 'rest')} shorter than the typical rest of "
                                 f"{shown(rest.typical)} h per hour of the shift before it",
                                 lines, len(rest.events), sum(past)))
    for person in sorted({event.person for event in grievances.disliked[worker]}):
        shifts = [event.shift for event in grievances.disliked[worker] if event.person == person]
        lines = tuple(describe_shift(context.shifts[shift]) + (HISTORY_MARK if in_history(context, shift) else "")
                      for shift in shifts)
        entries.append(CardEntry((DISLIKED_PARTNER, worker, person),
                                 f"disliked partner: {names[person]}, in {plural(len(shifts), 'shift')}", lines,
                                 len(shifts), sum(1 for shift in shifts if in_history(context, shift))))
    liked = grievances.liked[worker]
    if liked is not None:
        liked_names = ", ".join(names[person] for person in sorted(context.likes[worker]))
        lines = tuple(describe_shift(context.shifts[shift]) + " (with "
                      + ", ".join(names[other] for other in crews[shift] if other != worker) + ")"
                      + (HISTORY_MARK if in_history(context, shift) else "") for shift in liked.shifts)
        entries.append(CardEntry((MISSING_LIKE, worker, NO_PERSON),
                                 f"missing like: {plural(liked.events, 'shift')} with nobody they like (they like "
                                 f"{liked_names})", lines, liked.events,
                                 sum(1 for shift in liked.shifts if in_history(context, shift))))
    return entries


def grievance_card(context: AuditContext, crews: Sequence[tuple[int, ...]], report: GrievanceReport,
                   worker: int) -> str:
    """
    One worker's card: their facts, then each grievance with its events and fixes
    :param context: AuditContext
    :param crews: every shift's workers
    :param report: GrievanceReport
    :param worker: the worker's index
    :return: the card, as lines of text
    """
    names = [w.name for w in context.schedule_input.workers]
    facts = report.grievances.facts[worker]
    rests = ", ".join(f"{shown(rest.hours)} h" for rest in facts.rests) or "none"
    partners = ", ".join(f"{names[other]} ×{count}" for other, count in sorted(facts.partners.items())) or "none"
    lines = [f"{names[worker]}: {plural(len(facts.shifts), 'shift')}, {shown(facts.hours)} h; available "
             f"{shown(facts.availability)} h (of {shown(context.staffed_total)} h with a post staffed)",
             f"  rests: {rests}",
             f"  partners: {partners}; liked pairings: {facts.liked_pairings}"]
    entries = card_entries(context, crews, report.grievances, worker)
    lines.append("  grievances:" if entries else "  grievances: none")
    for entry in entries:
        lines.append(f"    - {entry.heading}")
        lines += [f"        {line}" for line in entry.event_lines]
        lines += [f"      {line}" for line in describe_fixes(context, report.fixes.get(entry.key), report.max_changes,
                                                             0 < entry.events == entry.in_history)]
    note = rest_note(report, worker)
    if note is not None:
        lines.append(f"  note: their shortest rest, at the typical rest, could have been longer at no one's expense "
                     f"({plural(len(note.steps), 'change')}): " + "; ".join(describe_step(context, step)
                                                                              for step in note.steps))
    return "\n".join(lines)


def rest_note(report: GrievanceReport, worker: int) -> NearbyFix | None:
    """The nearby schedule that would have given a worker a longer shortest rest at no one's expense (ADR 0055)."""
    found = report.fixes.get((LONGER_REST, worker, NO_PERSON))
    return found.harmless if found else None


FixCounts = dict[str, int]  # by FIX_COUNT_FIELDS
FIX_COUNT_FIELDS = ("events", "harmless", "transfers", "none", "history")  # a cell of the closing table


def tally(context: AuditContext, crews: Sequence[tuple[int, ...]],
          report: GrievanceReport) -> list[dict[str, FixCounts]]:
    """
    Each worker's events by kind: how many, and how many of them belong to a grievance with a harmless fix, with only
    transfers, or with no fix within the reach, and how many lie wholly in the history (whose fixes don't count)
    :return: per worker, in input order, the counts per kind
    """
    result = []
    for worker in range(len(context.schedule_input.workers)):
        counts = {kind: dict.fromkeys(FIX_COUNT_FIELDS, 0) for kind in KIND_ORDER}
        for entry in card_entries(context, crews, report.grievances, worker):
            cell = counts[entry.key[0]]
            cell["events"] += entry.events
            cell["history"] += entry.in_history
            found = report.fixes.get(entry.key)
            if report.max_changes > 0 and found is not None:
                reachable = entry.events - entry.in_history
                category = "harmless" if found.harmless else "transfers" if found.transfers else "none"
                cell[category] += reachable
        result.append(counts)
    return result


def tally_cell(count: FixCounts, searched: bool) -> str:
    """A cell of the closing table, e.g. '2 (1/1/0/0)'; just the events if there are none or the search was off."""
    if not count["events"] or not searched:
        return str(count["events"])
    return f"{count['events']} ({'/'.join(str(count[field]) for field in FIX_COUNT_FIELDS[1:])})"


def tally_heading(max_changes: int) -> str:
    """The closing table's heading, saying what the numbers in a cell's brackets are."""
    if max_changes <= 0:
        return "events by kind"
    return (f"events by kind (with a harmless fix / only transfers / no fix of up to {plural(max_changes, 'change')} / "
            f"in the history)")


def aligned(table: Sequence[Sequence[str]]) -> list[str]:
    """The rows of a table of text, each column as wide as its widest cell."""
    widths = [max(len(row[column]) for row in table) for column in range(len(table[0]))]
    return ["  ".join(text.ljust(width) for text, width in zip(row, widths)).rstrip() for row in table]


def describe_tally(context: AuditContext, counts: list[dict[str, FixCounts]], max_changes: int) -> str:
    """The closing table: each worker's events by kind, nothing added across kinds."""
    names = [worker.name for worker in context.schedule_input.workers]
    rows = [[name] + [tally_cell(worker_counts[kind], max_changes > 0) for kind in KIND_ORDER]
            for name, worker_counts in zip(names, counts)]
    return "\n".join([tally_heading(max_changes)] + aligned([[""] + list(KIND_ORDER)] + rows))


def report_text(context: AuditContext, assignment: Sequence[int], report: GrievanceReport) -> str:
    """The report as text: how far the fix search reached, a card per worker, then the closing table."""
    crews = workers_by_shift(context, assignment)
    reach = (f"fixes searched up to {plural(report.max_changes, 'change')}" if report.max_changes > 0
             else "fix search off")
    parts = [reach] + [grievance_card(context, crews, report, worker)
                       for worker in range(len(context.schedule_input.workers))]
    parts.append(describe_tally(context, tally(context, crews, report), report.max_changes))
    return "\n\n".join(parts)


def shift_json(context: AuditContext, shift: int) -> dict[str, Any]:
    """A shift for the JSON output."""
    time = context.shifts[shift].time
    return {"post": context.shifts[shift].post.name, "start": time.start.isoformat(), "end": time.end.isoformat(),
            "in_history": in_history(context, shift)}


def fix_json(context: AuditContext, fix: NearbyFix) -> dict[str, Any]:
    """A fix for the JSON output."""
    names = [worker.name for worker in context.schedule_input.workers]
    return {"changes": [describe_step(context, step) for step in fix.steps], "size": len(fix.steps),
            "removes": fix.removes,
            "creates": [{"kind": kind, "worker": names[worker],
                         "person": names[person] if person != NO_PERSON else None, "count": count}
                        for (kind, worker, person), count in fix.creates]}


def report_json(context: AuditContext, assignment: Sequence[int], report: GrievanceReport) -> dict[str, Any]:
    """
    The report as data for tools (ADR 0048): the reach, and per worker their facts and grievances, each with its
    events and fixes, and the closing counts
    """
    names = [worker.name for worker in context.schedule_input.workers]
    crews = workers_by_shift(context, assignment)
    counts = tally(context, crews, report)
    grievances = report.grievances
    workers = []
    for worker, name in enumerate(names):
        facts = grievances.facts[worker]
        entries = []
        for entry in card_entries(context, crews, grievances, worker):
            kind, _, person = entry.key
            found = report.fixes.get(entry.key)
            entries.append({"kind": kind, "person": names[person] if person != NO_PERSON else None,
                            "events": entry.events, "in_history": entry.in_history, "summary": entry.heading,
                            "event_lines": list(entry.event_lines),
                            "harmless": fix_json(context, found.harmless) if found and found.harmless else None,
                            "transfers": [fix_json(context, fix) for fix in found.transfers] if found else []})
        workers.append({
            "name": name, "shifts": [shift_json(context, shift) for shift in facts.shifts], "hours": facts.hours,
            "availability": facts.availability,
            "rests": [{"hours": rest.hours, "per_hour": rest.per_hour, "before": shift_json(context, rest.before),
                       "after": shift_json(context, rest.after)} for rest in facts.rests],
            "partners": {names[other]: count for other, count in sorted(facts.partners.items())},
            "liked_pairings": facts.liked_pairings, "grievances": entries, "counts": counts[worker],
            "longer_rest": fix_json(context, note) if (note := rest_note(report, worker)) else None})
    return {"max_changes": report.max_changes, "fixed_slots": context.fixed_slots,
            "staffed_hours": context.staffed_total, "workers": workers}


# --- measures per kind, for the tools that read the audit (docs/explanation/tuning.md#reading-the-audit) ---

KIND_MEASURES = ("harmless", "most", "events")  # per kind, in the reading's order: the events with a harmless fix, the
                                                # most aggrieved worker's events, all events
HOURS_KINDS = (LOAD, REST)                      # the kinds also measured in hours (ADR 0051): load in extra hours, rest
HOURS_UNITS = {LOAD: "h more", REST: "h short"}  # in hours short, as these units say
HOURS_MEASURES = ("hours_harmless", "hours_most", "hours")  # the same three as KIND_MEASURES, in those hours
LONGER_REST_MEASURE = "longer"                  # rest's own extra measure (ADR 0055): how many workers' shortest rests
                                                # could have been longer at no one's expense


@dataclass(frozen=True, slots=True)
class WorkerTally:
    """
    One worker's row of the closing table (their counts by kind), with their events in hours for each of HOURS_KINDS:
    in all, and those of a grievance with a harmless fix (leaving out events wholly in the history, as the table does);
    and whether their shortest rest could have been longer at no one's expense (ADR 0055)
    """
    name: str
    counts: dict[str, FixCounts]
    hours: dict[str, float]
    hours_harmless: dict[str, float]
    longer_rest: bool = False


def has_harmless_fix(report: GrievanceReport, key: GrievanceKey) -> bool:
    """True if the fix search ran and found a harmless fix for a grievance."""
    found = report.fixes.get(key)
    return report.max_changes > 0 and found is not None and found.harmless is not None


def worker_tallies(context: AuditContext, assignment: Sequence[int], report: GrievanceReport) -> list[WorkerTally]:
    """
    Every worker's row of the closing table, with their load in extra hours (above their share, ADR 0053) and their
    rest events in hours short (how much longer each rest would have to be to reach the typical rest, ADR 0054,
    added within the one kind)
    :param context: AuditContext
    :param assignment: the audited schedule, a worker per slot
    :param report: its GrievanceReport
    :return: a WorkerTally per worker, in input order
    """
    counts = tally(context, workers_by_shift(context, assignment), report)
    result = []
    for worker, name in enumerate(worker.name for worker in context.schedule_input.workers):
        load = report.grievances.load[worker]
        extra = load.extra_hours if load is not None else 0.0
        rest = report.grievances.rest[worker]
        events = rest.events if rest is not None else ()
        reachable = [event.shortfall for event in events
                     if not (in_history(context, event.rest.before) and in_history(context, event.rest.after))]
        result.append(WorkerTally(
            name, counts[worker], {LOAD: extra, REST: math.fsum(event.shortfall for event in events)},
            {LOAD: extra if has_harmless_fix(report, (LOAD, worker, NO_PERSON)) else 0.0,
             REST: math.fsum(reachable) if has_harmless_fix(report, (REST, worker, NO_PERSON)) else 0.0},
            rest_note(report, worker) is not None))
    return result


def kind_measures(tallies: Sequence[WorkerTally]) -> dict[str, dict[str, float]]:
    """
    Each kind's measures, which the tools reading the audit compare: the events with a harmless fix, the most
    aggrieved worker's events and all events (KIND_MEASURES); for load and rest, the same three in hours too
    (HOURS_MEASURES, in HOURS_UNITS); for rest, also how many workers' shortest rests could have been longer
    (LONGER_REST_MEASURE, ADR 0055). Nothing is added across kinds, and the report itself never shows these.
    :param tallies: every worker's WorkerTally
    :return: per kind (in KIND_ORDER), per measure
    """
    result: dict[str, dict[str, float]] = {}
    for kind in KIND_ORDER:
        cells = [tallied.counts[kind] for tallied in tallies]
        result[kind] = {"harmless": sum(cell["harmless"] for cell in cells),
                        "most": max((cell["events"] for cell in cells), default=0),
                        "events": sum(cell["events"] for cell in cells)}
    for kind in HOURS_KINDS:
        result[kind] |= {"hours_harmless": math.fsum(tallied.hours_harmless[kind] for tallied in tallies),
                         "hours_most": max((tallied.hours[kind] for tallied in tallies), default=0.0),
                         "hours": math.fsum(tallied.hours[kind] for tallied in tallies)}
    result[REST][LONGER_REST_MEASURE] = sum(tallied.longer_rest for tallied in tallies)
    return result


def audit_measures(context: AuditContext, assignment: Sequence[int],
                   max_changes: int = DEFAULT_MAX_CHANGES) -> tuple[list[WorkerTally], dict[str, dict[str, float]]]:
    """
    Audit a schedule for a tool: every worker's row of the closing table and each kind's measures
    :param context: AuditContext
    :param assignment: a worker index per slot, which must be legal
    :param max_changes: how far the fix search reaches; 0 turns it off
    :return: (a WorkerTally per worker, the measures per kind)
    """
    tallies = worker_tallies(context, assignment, report_grievances(context, assignment, max_changes))
    return tallies, kind_measures(tallies)


# --- command line ---

def audit_schedule(schedule_input: ScheduleInput, schedule_path: pathlib.Path,
                   max_changes: int = DEFAULT_MAX_CHANGES, as_json: bool = False) -> str:
    """
    Audit a written schedule; with a history, together with it, as one schedule whose history no fix may change
    :param schedule_input: ScheduleInput the schedule was made for
    :param schedule_path: pathlib.Path of the schedule file (CSV, XLSX or ODS)
    :param max_changes: how far the fix search reaches; 0 turns it off
    :param as_json: True for the report as JSON, for tools
    :return: the report: how far the fix search reached, a card per worker and the closing table (or the same as JSON)
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
    report = report_grievances(context, assignment, max_changes)
    if as_json:
        return json.dumps({"history_schedules": len(schedule_input.history),
                           **report_json(context, assignment, report)}, indent=JSON_INDENT)
    text = report_text(context, assignment, report)
    if schedule_input.history:
        text = (f"together with its history: {len(schedule_input.history)} previous schedule(s), "
                f"{context.fixed_slots} slots that no fix may change\n\n" + text)
    return text


def non_negative(text: str) -> int:
    """A whole number of at least 0, for the command line."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be at least 0, got {value}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the audit from the command line
    :param argv: the arguments, without the program name; None means sys.argv[1:]
    :return: the exit code
    """
    parser = argparse.ArgumentParser(prog="audit", description="Audit a schedule from each worker's point of view.")
    parser.add_argument("input", help="the YAML input file")
    parser.add_argument("schedule", help="the schedule written for it (CSV, XLSX or ODS)")
    parser.add_argument("--max-changes", type=non_negative, default=DEFAULT_MAX_CHANGES, metavar="K",
                        help=f"how many moves and swaps the fix search reaches (default {DEFAULT_MAX_CHANGES}); 0 "
                             "turns it off. Each change more multiplies the time by about the number of legal changes")
    parser.add_argument("--json", action="store_true", help="print the report as JSON, for tools")
    arguments = parser.parse_args(argv)
    try:
        print(audit_schedule(read_input(arguments.input), pathlib.Path(arguments.schedule), arguments.max_changes,
                             arguments.json))
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
