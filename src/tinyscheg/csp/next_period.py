"""
The next period: whether a schedule leaves the period after it a legal schedule (ADR 0042). The next period is the
same input a whole number of days later, so that it covers the same hours, with the schedule as the last part of its
history; checking it is a search for any legal schedule, not the best, with a limit on its nodes.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import math
from collections.abc import Sequence

from tinyscheg.csp.problem import Problem, build_problem, unfillable_slots
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.schedule_input import PreviousSchedule, ScheduleInput
from tinyscheg.timing.datetime_range import DateTimeRange

# The next period starts the first whole number of these after this period's start that isn't before its end (the
# user, 2026-11-16): right after a period of whole days, the next day at the same time after a 16-hour one
NEXT_PERIOD_STEP = dt.timedelta(days=1)
# The most nodes the check's search may visit before giving up undecided: about 3 seconds on CPython at worst, and
# well under one on PyPy (measured 2026-11-16); the benchmark's cases needed 1-23
NEXT_PERIOD_CHECK_NODES = 500_000
THIS_PERIOD = "the schedule just made"  # the history entry's source, for messages about the next period


class NextPeriodCheck(enum.Enum):
    """Whether the next period can still be filled after a schedule."""
    FILLABLE = "fillable"
    NOT_FILLABLE = "not fillable"
    UNDECIDED = "undecided"  # the check reached its node limit first


def next_period_offset(schedule_input: ScheduleInput) -> dt.timedelta:
    """
    How much later the next period starts than this one: the first whole number of NEXT_PERIOD_STEPs that isn't
    shorter than this period
    :param schedule_input: ScheduleInput of this period
    :return: the offset, a timedelta
    """
    return math.ceil(schedule_input.settings.period.duration / NEXT_PERIOD_STEP) * NEXT_PERIOD_STEP


def next_period_input(schedule_input: ScheduleInput, assignment: Sequence[int],
                      source: str = THIS_PERIOD) -> ScheduleInput:
    """
    The next period's input: the same parameters (workers, posts, rules, period length) a next_period_offset later,
    each worker's unavailability repeated as much later, and this period's schedule added to the history
    :param schedule_input: ScheduleInput of this period
    :param assignment: this period's schedule, a worker index (into schedule_input's workers) for each of its slots, in
    stable slot order
    :param source: what the history entry is called in messages
    :return: ScheduleInput of the next period
    """
    offset = next_period_offset(schedule_input)

    def later(time: DateTimeRange) -> DateTimeRange:
        return DateTimeRange(time.start + offset, time.end + offset)
    workers = tuple(dataclasses.replace(worker, unavailable=tuple(later(away) for away in worker.unavailable))
                    for worker in schedule_input.workers)
    settings = dataclasses.replace(schedule_input.settings, period=later(schedule_input.settings.period))
    history = (*schedule_input.history, PreviousSchedule(source, schedule_input, tuple(assignment)))
    return dataclasses.replace(schedule_input, settings=settings, workers=workers, history=history)


def check_next_period(schedule_input: ScheduleInput, problem: Problem, assignment: Sequence[int],
                      max_nodes: int = NEXT_PERIOD_CHECK_NODES) -> NextPeriodCheck:
    """
    Check whether the next period could still be filled after a schedule
    :param schedule_input: ScheduleInput of this period
    :param problem: its Problem
    :param assignment: the schedule found for it, a worker index per slot of the problem (its history included)
    :param max_nodes: the most nodes the check's search may visit
    :return: NextPeriodCheck
    """
    this_period = [assignment[slot.index] for slot in problem.new_slots]
    following = build_problem(next_period_input(schedule_input, this_period))
    if unfillable_slots(following):
        return NextPeriodCheck.NOT_FILLABLE
    result = find_first_schedule(following, max_nodes)
    if result.assignment is not None:
        return NextPeriodCheck.FILLABLE
    return NextPeriodCheck.NOT_FILLABLE if result.complete else NextPeriodCheck.UNDECIDED
