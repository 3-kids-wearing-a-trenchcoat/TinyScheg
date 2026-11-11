"""
The schedule audit (docs/explanation/schedule-audit.md): a finished schedule judged the way its workers would, each
compared with the others. A development tool, independent of tinyscheg.csp and tinyscheg.scoring.
Usage: PYTHONPATH=src python tools/audit.py INPUT SCHEDULE
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import pathlib
import sys
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from schedule_checker import hard_constraint_violations
from schedule_reader import ScheduleReadError, read_schedule
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.validation import InputError
from tinyscheg.timing.datetime_range import DateTimeRange

TOLERANCE = 1                               # a gap of one (shift, short straw, ...) is tolerated; more is a complaint
DAY_BOUNDARY = dt.time(0, 0)                # days, the windows load is compared over, start at this time
SHORT_REST_MARGIN = dt.timedelta(hours=2)   # a rest shorter than min_rest plus this is a short straw
MAX_CHANGES = 3                             # an easy fix is a chain of at most this many moves and swaps
SEVERITY_EPSILON = 1e-9                     # severities closer than this are equal (hours are divided as floats)
SHOWN_DECIMALS = 2                          # decimals shown for hours and severities

WHOLE_PERIOD = "overall"                    # the label of the window covering the whole period

LOAD = "load"
SHORT_STRAWS = "short straws"
LIKED_PARTNERS = "liked partners"

SHORT_REST = "short rest"
HEAVIEST_DAY = "heaviest day"
DISLIKED_PARTNER = "disliked partner"
STRAW_KINDS = (SHORT_REST, HEAVIEST_DAY, DISLIKED_PARTNER)

EXIT_SUCCESS = 0
EXIT_ILLEGAL = 1  # the schedule breaks a hard constraint, so there's nothing to audit
EXIT_USAGE = 2    # invalid arguments, or the files couldn't be read or don't match


# --- the fixed part: windows and availability ---

@dataclass(frozen=True, slots=True)
class Window:
    """A stretch of time load is compared over: a day, or the whole period."""
    label: str
    time: DateTimeRange


@dataclass(frozen=True, slots=True)
class AuditContext:
    """
    Everything about an input that doesn't depend on the assignment, computed once.
    availability[w][label] is worker w's available hours in that window; longest[label] the length in hours of the
    longest shift starting in it (windows without shifts are left out).
    """
    schedule_input: ScheduleInput
    shifts: tuple[Shift, ...]
    slots: tuple[Slot, ...]
    windows: tuple[Window, ...]
    shift_day: tuple[str, ...]
    availability: tuple[dict[str, float], ...]
    longest: dict[str, float]
    likes: tuple[frozenset[int], ...]
    dislikes: tuple[frozenset[int], ...]


def hours(length: dt.timedelta) -> float:
    """A datetime.timedelta in hours."""
    return length / dt.timedelta(hours=1)


def day_start(moment: dt.datetime) -> dt.datetime:
    """The start of the day (beginning at DAY_BOUNDARY) that a moment falls in."""
    start = dt.datetime.combine(moment.date(), DAY_BOUNDARY)
    return start if start <= moment else start - dt.timedelta(days=1)


def days(period: DateTimeRange) -> list[Window]:
    """The days the period touches, each labelled with the date it starts on."""
    result = []
    start = day_start(period.start)
    while start < period.end:
        result.append(Window(start.date().isoformat(), DateTimeRange(start, start + dt.timedelta(days=1))))
        start += dt.timedelta(days=1)
    return result


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


def build_context(schedule_input: ScheduleInput, shifts: Sequence[Shift], slots: Sequence[Slot]) -> AuditContext:
    """
    Compute what the audit needs about an input, whatever the assignment
    :param schedule_input: ScheduleInput
    :param shifts: the shifts in stable order
    :param slots: the slots in stable order
    :return: the AuditContext
    """
    period = schedule_input.settings.period
    windows = tuple(days(period)) + (Window(WHOLE_PERIOD, period),)
    shift_day = tuple(day_start(shift.time.start).date().isoformat() for shift in shifts)
    longest: dict[str, float] = {}
    for shift, day in zip(shifts, shift_day):
        for label in (day, WHOLE_PERIOD):
            longest[label] = max(longest.get(label, 0.0), hours(shift.time.duration))
    index_of = {worker.name: index for index, worker in enumerate(schedule_input.workers)}
    return AuditContext(
        schedule_input=schedule_input, shifts=tuple(shifts), slots=tuple(slots), windows=windows,
        shift_day=shift_day,
        availability=tuple({window.label: available_hours(worker.unavailable, window.time, period)
                            for window in windows} for worker in schedule_input.workers),
        longest=longest,
        likes=tuple(frozenset(index_of[name] for name in worker.likes) for worker in schedule_input.workers),
        dislikes=tuple(frozenset(index_of[name] for name in worker.dislikes) for worker in schedule_input.workers))


# --- each worker's statistics ---

@dataclass(frozen=True, slots=True)
class WorkerStats:
    """
    One worker's side of a schedule. shift_count and shift_hours are per window label; rests are in hours, in time
    order; partners counts the shifts shared with each other worker; straws counts each kind of short straw.
    """
    shifts: tuple[int, ...]
    shift_count: dict[str, int]
    shift_hours: dict[str, float]
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


def worker_stats(context: AuditContext, assignment: Sequence[int]) -> tuple[WorkerStats, ...]:
    """
    Every worker's statistics
    :param context: AuditContext
    :param assignment: a worker index per slot
    :return: a WorkerStats per worker, in input order
    """
    crews = workers_by_shift(context, assignment)
    worker_count = len(context.schedule_input.workers)
    heaviest = _heaviest_day_straws(context, crews, worker_count)
    return tuple(_one_worker(context, crews, worker, heaviest[worker]) for worker in range(worker_count))


def _one_worker(context: AuditContext, crews: list[tuple[int, ...]], worker: int, heaviest_days: int) -> WorkerStats:
    """The statistics of one worker, given every shift's crew and how many heaviest days they had."""
    own = tuple(index for index, crew in enumerate(crews) if worker in crew)  # stable order is time order
    count: Counter[str] = Counter()
    worked: Counter[str] = Counter()
    for index in own:
        for label in (context.shift_day[index], WHOLE_PERIOD):
            count[label] += 1
            worked[label] += hours(context.shifts[index].time.duration)
    times = sorted(context.shifts[index].time for index in own)
    rests = tuple(hours(later.start - earlier.end) for earlier, later in zip(times, times[1:]))
    partners: Counter[int] = Counter(other for index in own for other in set(crews[index]) if other != worker)
    liked = sum(1 for index in own if context.likes[worker] & set(crews[index]))
    disliked = sum(1 for index in own if context.dislikes[worker] & set(crews[index]))
    short_rest = hours(context.schedule_input.settings.min_rest + SHORT_REST_MARGIN)
    straws = {SHORT_REST: sum(1 for rest in rests if rest < short_rest), HEAVIEST_DAY: heaviest_days,
              DISLIKED_PARTNER: disliked}
    return WorkerStats(own, dict(count), dict(worked), rests, dict(partners), liked, disliked, straws)


def _heaviest_day_straws(context: AuditContext, crews: list[tuple[int, ...]], worker_count: int) -> list[int]:
    """
    How many days each worker had the most shifts of anyone available that day, counting only days on which not
    everyone available did the same number
    """
    straws = [0] * worker_count
    for window in context.windows:
        if window.label == WHOLE_PERIOD:
            continue
        present = [worker for worker in range(worker_count) if context.availability[worker][window.label] > 0]
        count = Counter(worker for index, crew in enumerate(crews) if context.shift_day[index] == window.label
                        for worker in set(crew))
        loads = [count[worker] for worker in present]
        if loads and max(loads) > min(loads):
            for worker in present:
                straws[worker] += count[worker] == max(loads)
    return straws


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
    """A schedule's audit: every worker's statistics and every complaint, most severe first."""
    stats: tuple[WorkerStats, ...]
    complaints: tuple[Complaint, ...]


def is_peer(context: AuditContext, worker: int, other: int, label: str) -> bool:
    """True if the other worker was available at least as long as the worker in the window, and for some time."""
    other_hours = context.availability[other][label]
    return other != worker and other_hours > 0 and other_hours >= context.availability[worker][label]


def evaluate(context: AuditContext, assignment: Sequence[int]) -> Audit:
    """
    Audit a schedule
    :param context: AuditContext
    :param assignment: a worker index per slot
    :return: the Audit
    """
    stats = worker_stats(context, assignment)
    complaints = _load_complaints(context, stats) + _straw_complaints(context, stats) + _liked_complaints(context,
                                                                                                         stats)
    return Audit(stats, tuple(sorted(complaints, key=lambda c: (-c.severity, c.worker, c.kind, c.window, c.against))))


def _pairs(context: AuditContext, label: str) -> Iterator[tuple[int, int]]:
    """Every (worker, peer) pair for a window."""
    for worker, other in itertools.permutations(range(len(context.schedule_input.workers)), 2):
        if is_peer(context, worker, other, label):
            yield worker, other


def _load_complaints(context: AuditContext, stats: tuple[WorkerStats, ...]) -> list[Complaint]:
    """Load complaints, per day and overall: the gap in shifts, or in hours over the window's longest shift."""
    result = []
    for window in context.windows:
        longest = context.longest.get(window.label)
        if longest is None:
            continue
        for worker, other in _pairs(context, window.label):
            mine, theirs = stats[worker], stats[other]
            gap = max(mine.shift_count.get(window.label, 0) - theirs.shift_count.get(window.label, 0),
                      (mine.shift_hours.get(window.label, 0.0) - theirs.shift_hours.get(window.label, 0.0)) / longest)
            if gap > TOLERANCE + SEVERITY_EPSILON:
                result.append(Complaint(LOAD, worker, other, window.label, gap))
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
    for slot in context.slots:
        for worker in range(len(names)):
            if worker != assignment[slot.index]:
                changed = list(assignment)
                changed[slot.index] = worker
                yield Change(f"giving {names[worker]} {describe_shift(context.shifts[slot.shift_index])} instead of "
                             f"{names[assignment[slot.index]]}", tuple(changed), (slot.index,))
    for first, second in itertools.combinations(context.slots, 2):
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
        if any(later.start - earlier.end < min_rest for earlier, later in zip(times, times[1:])):
            return False
    return True


def is_harmless(before: dict[tuple[str, int, int, str], float], after: Audit) -> bool:
    """
    True if a change creates no new complaint and makes no existing one more severe
    :param before: each complaint's severity before the change, by key
    :param after: the Audit after the change
    """
    return all(complaint.key in before and complaint.severity <= before[complaint.key] + SEVERITY_EPSILON
               for complaint in after.complaints)


ComplaintKey = tuple[str, int, int, str]


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


def harmless_steps(context: AuditContext, assignment: tuple[int, ...],
                   before: dict[ComplaintKey, float]) -> list[_Step]:
    """
    Every legal move and swap from a schedule that is harmless compared with the audited schedule
    :param context: AuditContext
    :param assignment: the schedule to change, which must be legal
    :param before: each complaint's severity in the audited schedule, by key
    :return: the harmless steps, in candidate_changes' order
    """
    steps = []
    own_slots = slots_by_worker(assignment, len(context.schedule_input.workers))
    for change in candidate_changes(context, assignment):
        if not is_legal_change(context, own_slots, change):
            continue
        after = evaluate(context, change.assignment)
        if is_harmless(before, after):
            steps.append(_Step(change, after))
    return steps


def _fix_chain(context: AuditContext, before: dict[ComplaintKey, float], key: ComplaintKey,
               first_steps: list[_Step]) -> tuple[_Step, ...] | None:
    """
    Look for an easy fix for one complaint, greedily: at each step, take the harmless change that lowers the
    complaint's severity most (the first of equals), until it's gone or MAX_CHANGES changes are made
    :param context: AuditContext
    :param before: each complaint's severity in the audited schedule, by key
    :param key: the complaint to fix
    :param first_steps: the harmless steps from the audited schedule (shared between complaints)
    :return: the chain of steps, or None if no easy fix was found
    """
    chain: list[_Step] = []
    current, options = before[key], first_steps
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
    before = {complaint.key: complaint.severity for complaint in audit.complaints}
    if not before:
        return {}
    first_steps = harmless_steps(context, assignment, before)
    fixes: dict[ComplaintKey, Fix] = {}
    for step in first_steps:
        for key in before.keys() - fixes.keys():
            if step.removes(key):
                fixes[key] = Fix((step.change,))
    for complaint in audit.complaints:  # most severe first
        if complaint.key in fixes:
            continue
        chain = _fix_chain(context, before, complaint.key, first_steps)
        if chain is None:
            continue
        fix = Fix(tuple(step.change for step in chain))
        for key in before.keys() - fixes.keys():
            if chain[-1].removes(key):
                fixes[key] = fix
    return fixes


# --- the report ---

@dataclass(frozen=True, slots=True)
class AuditSummary:
    """
    The group summary: how many complaints there are and how many have an easy fix, the severity of those with and
    without one, and severity_by_worker, each worker's total as (worker, severity), most first.
    """
    complaints: int
    easy_fixes: int
    easy_fix_severity: float
    no_fix_severity: float
    aggrieved: int
    concentration: float
    severity_by_worker: tuple[tuple[int, float], ...]


def summarize(audit: Audit, fixes: dict[ComplaintKey, Fix]) -> AuditSummary:
    """
    Summarize an audit for the group
    :param audit: Audit
    :param fixes: the fixes found, by complaint key
    :return: the AuditSummary; concentration is the most aggrieved worker's share of all severity (0 if none)
    """
    by_worker: Counter[int] = Counter()
    for complaint in audit.complaints:
        by_worker[complaint.worker] += complaint.severity
    total = sum(by_worker.values())
    fixable = [complaint for complaint in audit.complaints if complaint.key in fixes]
    ranked = tuple(sorted(by_worker.items(), key=lambda item: (-item[1], item[0])))
    fixable_severity = sum(complaint.severity for complaint in fixable)
    return AuditSummary(complaints=len(audit.complaints), easy_fixes=len(fixable), easy_fix_severity=fixable_severity,
                        no_fix_severity=total - fixable_severity,
                        aggrieved=len(by_worker), concentration=ranked[0][1] / total if total else 0.0,
                        severity_by_worker=ranked)


def shown(value: float) -> str:
    """A number for the report, with at most SHOWN_DECIMALS decimals."""
    return f"{round(value, SHOWN_DECIMALS):g}"


def describe_complaint(context: AuditContext, audit: Audit, complaint: Complaint) -> str:
    """A complaint in the worker's terms, e.g. 'load on 2025-01-01: 4 shifts (16 h), against Bob's 2 (8 h)'."""
    other = context.schedule_input.workers[complaint.against].name
    mine, theirs = audit.stats[complaint.worker], audit.stats[complaint.against]
    if complaint.kind == LOAD:
        label = complaint.window
        when = "overall" if label == WHOLE_PERIOD else f"on {label}"
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
    for window in context.windows[:-1]:
        lines.append(f"  {window.label}: {stats.shift_count.get(window.label, 0)} shifts, "
                     f"{shown(stats.shift_hours.get(window.label, 0.0))} h; available "
                     f"{shown(availability[window.label])} h")
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
    ])


# --- command line ---

def audit_schedule(schedule_input: ScheduleInput, schedule_path: pathlib.Path) -> str:
    """
    Audit a written schedule
    :param schedule_input: ScheduleInput the schedule was made for
    :param schedule_path: pathlib.Path of the CSV schedule
    :return: the report: a card per worker, then the group summary
    :raises ScheduleReadError: if the file doesn't match the input
    :raises ValueError: if the schedule breaks a hard constraint
    """
    read = read_schedule(schedule_path, schedule_input)
    violations = hard_constraint_violations(schedule_input, read.slots, read.assignment)
    if violations:
        raise ValueError("the schedule breaks hard constraints:\n" + "\n".join(f"  - {v}" for v in violations))
    context = build_context(schedule_input, read.shifts, read.slots)
    audit = evaluate(context, read.assignment)
    fixes = find_fixes(context, read.assignment, audit)
    cards = [card(context, audit, fixes, worker) for worker in range(len(schedule_input.workers))]
    return "\n\n".join(cards + [describe_summary(context, summarize(audit, fixes))])


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the audit from the command line
    :param argv: the arguments, without the program name; None means sys.argv[1:]
    :return: the exit code
    """
    parser = argparse.ArgumentParser(prog="audit", description="Audit a schedule from each worker's point of view.")
    parser.add_argument("input", help="the YAML input file")
    parser.add_argument("schedule", help="the CSV schedule written for it")
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
