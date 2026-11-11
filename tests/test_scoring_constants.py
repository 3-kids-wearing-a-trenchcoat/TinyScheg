"""Tests for tinyscheg.scoring.constants."""
import datetime as dt
import itertools
import pathlib
import random

import pytest

from tinyscheg.csp.problem import build_problem
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, ScoringParameters, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.constants import (availability, build_constants, hours, packable_hours, workload_scale,
                                         worst_deficit)
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"


def at(hour: float) -> dt.datetime:
    """A datetime that many hours after 2025-01-01 00:00."""
    return dt.datetime(2025, 1, 1) + dt.timedelta(hours=hour)


def span(start: float, end: float) -> DateTimeRange:
    """A range from start to end, in hours after 2025-01-01 00:00."""
    return DateTimeRange(at(start), at(end))


# --- availability ---

def test_availability_subtracts_unavailability_within_the_period() -> None:
    worker = Worker("Anne", unavailable=(span(-5, 2), span(10, 12)))  # the first starts before the period
    assert availability(worker, span(0, 24)) == 24 - 2 - 2


def test_overlapping_unavailability_counts_once() -> None:
    worker = Worker("Anne", unavailable=(span(2, 6), span(4, 8), span(5, 7), span(20, 30)))
    assert availability(worker, span(0, 24)) == 24 - 6 - 4


def test_fully_available_and_never_available() -> None:
    assert availability(Worker("Anne"), span(0, 24)) == 24
    assert availability(Worker("Bob", unavailable=(span(-1, 25),)), span(0, 24)) == 0


# --- packable hours and worst deficit ---

def brute_force(ranges: list[DateTimeRange], min_rest: float, rest_factor: float) -> tuple[float, float]:
    """The most hours and the largest deficit over every legal sequence of the ranges, by trying them all."""
    most_hours = largest_deficit = 0.0
    for size in range(1, len(ranges) + 1):
        for sequence in itertools.combinations(ranges, size):  # ranges are sorted, so combinations are in time order
            gaps = [hours(later.start - earlier.end) for earlier, later in zip(sequence, sequence[1:])]
            if any(gap < min_rest for gap in gaps):
                continue
            most_hours = max(most_hours, sum(hours(time.duration) for time in sequence))
            deficit = sum(max(0.0, rest_factor * hours(earlier.duration) - gap)
                          for earlier, gap in zip(sequence, gaps))
            largest_deficit = max(largest_deficit, deficit)
    return most_hours, largest_deficit


def test_packable_hours_by_hand() -> None:
    # 0-4 and 10-14 fit together with 6 hours' rest; 4-8 fits with neither
    ranges = [span(0, 4), span(4, 8), span(10, 14)]
    assert packable_hours(ranges, 6) == 8
    assert packable_hours(ranges, 0) == 12  # back to back is allowed with no minimum rest


def test_worst_deficit_by_hand() -> None:
    # a 4-hour shift with a target of 12 hours' rest: 0-4 then 10-14 leaves 6 hours, 6 short
    assert worst_deficit([span(0, 4), span(10, 14)], 6, 3) == 6
    assert worst_deficit([span(0, 4), span(10, 14)], 6, 1.5) == 0  # the target is met by the minimum rest
    assert worst_deficit([span(0, 4)], 6, 3) == 0                 # a single shift has no rest after it


def test_empty_domain() -> None:
    assert packable_hours([], 6) == 0 and worst_deficit([], 6, 3) == 0


@pytest.mark.parametrize("seed", range(20))
def test_maxima_match_brute_force(seed: int) -> None:
    generator = random.Random(seed)
    starts = sorted(generator.sample(range(0, 40), 9))
    ranges = sorted({span(start, start + generator.choice([2, 3, 4, 6])) for start in starts})
    min_rest, rest_factor = generator.choice([0, 3, 6]), generator.choice([1, 2, 3])
    expected_hours, expected_deficit = brute_force(ranges, min_rest, rest_factor)
    assert packable_hours(ranges, min_rest) == pytest.approx(expected_hours)
    assert worst_deficit(ranges, min_rest, rest_factor) == pytest.approx(expected_deficit)


# --- the constants of a run ---

def test_example_constants() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    assert constants.parameters == ScoringParameters()
    assert constants.min_rest == 6
    assert constants.shared_slots == 26          # 13 night shifts of the front gate, 2 workers each
    assert len(constants.slot_hours) == 47 and sum(constants.slot_hours) == 144
    jack, jill = constants.workers[:2]
    assert jack.availability == 72 - 4           # 04:00-06:00 on two days
    assert jill.availability == 72 - 24          # all of the 3rd
    assert jack.likes == frozenset({1}) and constants.workers[2].dislikes == frozenset({0, 1})
    assert all(worker.packable_hours <= worker.availability for worker in constants.workers)
    assert constants.workload_scale == pytest.approx(workload_scale(constants.workers, 2))


def test_workers_with_no_availability_are_left_out_of_the_scale() -> None:
    period = span(0, 8)
    post = Post("desk", ShiftRules(dt.timedelta(hours=4), (("any", 1),)))
    away = Worker("Bob", unavailable=(span(0, 8),))
    schedule_input = ScheduleInput(Settings(period, dt.timedelta(hours=4)), (Worker("Anne"), away), (post,))
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    anne, bob = constants.workers
    assert (bob.availability, bob.packable_hours) == (0, 0)
    assert anne.packable_hours == 4                       # 0-4 and 4-8 are only 0 hours apart
    assert constants.workload_scale == 8 * (4 / 8) ** 2   # Bob doesn't count
    assert constants.shared_slots == 0
