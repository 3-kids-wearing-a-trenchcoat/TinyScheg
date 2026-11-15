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
from tinyscheg.scoring.constants import (DISLIKED_PARTNER, LIKED_PARTNER, availability, build_constants, hours,
                                         like_value, load_classes, rest_factor, rest_unit, slot_load,
                                         unavailable_before, workload_unit, worst_deficit)
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


# --- worst deficit ---

def brute_force(ranges: list[DateTimeRange], min_rest: float, factor: float,
                unavailable: tuple[DateTimeRange, ...] = ()) -> float:
    """The largest deficit over every legal sequence of the ranges, by trying them all; a rest counts only the time
    outside the unavailability (checked hour by hour, the ranges being on whole hours)."""
    largest_deficit = 0.0
    for size in range(1, len(ranges) + 1):
        for sequence in itertools.combinations(ranges, size):  # ranges are sorted, so combinations are in time order
            pairs = list(zip(sequence, sequence[1:]))
            if any(not 0 < hours(later.start - earlier.end) >= min_rest for earlier, later in pairs):
                continue  # too close on the clock, or back to back
            rests = [sum(1 for hour in range(int(hours(earlier.end - at(0))), int(hours(later.start - at(0))))
                         if not any(away.overlaps(span(hour, hour + 1)) for away in unavailable))
                     for earlier, later in pairs]
            deficit = sum(max(0.0, factor * (hours(earlier.duration) + hours(later.duration)) / 2 - rest)
                          for (earlier, later), rest in zip(pairs, rests))
            largest_deficit = max(largest_deficit, deficit)
    return largest_deficit


def test_worst_deficit_by_hand() -> None:
    # a 4-hour shift with a target of 12 hours' rest: 0-4 then 10-14 leaves 6 hours, 6 short
    assert worst_deficit([span(0, 4), span(10, 14)], 6, 3) == 6
    assert worst_deficit([span(0, 4), span(10, 14)], 6, 1.5) == 0  # the target is met by the minimum rest
    assert worst_deficit([span(0, 4)], 6, 3) == 0                 # a single shift has no rest after it
    # shifts of different lengths: the target is gamma times their mean length, 2 * (2 + 8) / 2 = 10 hours
    assert worst_deficit([span(0, 2), span(8, 16)], 6, 2) == 4


def test_unavailable_hours_before_a_moment() -> None:
    # ADR 0038: overlapping unavailability counts once; only the part before the moment counts
    away = tuple(sorted((span(2, 6), span(4, 8), span(20, 22))))
    assert unavailable_before(away, at(5)) == 3
    assert unavailable_before(away, at(10)) == 6
    assert unavailable_before(away, at(24)) == 8
    assert unavailable_before((), at(24)) == 0


@pytest.mark.parametrize("seed", range(20))
def test_worst_deficit_with_unavailability_matches_brute_force(seed: int) -> None:
    # ADR 0038: rests count only available time, while which sequences are legal stays on the clock
    generator = random.Random(1000 + seed)
    starts = sorted(generator.sample(range(0, 40), 9))
    ranges = sorted({span(start, start + generator.choice([2, 3, 4])) for start in starts})
    away_start = generator.randrange(0, 40)
    away = (span(away_start, away_start + generator.choice([2, 4, 8])),)
    ranges = [time for time in ranges if not time.overlaps(away[0])]  # a worker is available for their shifts
    min_rest, factor = generator.choice([0, 3, 6]), generator.choice([1, 2, 3])
    assert worst_deficit(ranges, min_rest, factor, away) == pytest.approx(brute_force(ranges, min_rest, factor, away))


def test_rest_factor_is_the_free_hours_per_hour_of_work() -> None:
    # ADR 0036: three workers available 24 hours each, 8 hours of slots: (72 - 8) / 8
    assert rest_factor([24, 24, 24], [4, 4]) == 8
    assert rest_factor([24], []) == 0  # no slots, no rest to judge


def test_empty_domain() -> None:
    assert worst_deficit([], 6, 3) == 0


@pytest.mark.parametrize("seed", range(20))
def test_worst_deficit_matches_brute_force(seed: int) -> None:
    generator = random.Random(seed)
    starts = sorted(generator.sample(range(0, 40), 9))
    ranges = sorted({span(start, start + generator.choice([2, 3, 4, 6])) for start in starts})
    min_rest, factor = generator.choice([0, 3, 6]), generator.choice([1, 2, 3])
    expected_deficit = brute_force(ranges, min_rest, factor)
    assert worst_deficit(ranges, min_rest, factor) == pytest.approx(expected_deficit)


# --- the constants of a run ---

def test_example_constants() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    assert constants.parameters == ScoringParameters()
    assert constants.min_rest == 6
    assert constants.shared_slots == 10          # 5 night shifts of the front gate, 2 workers each
    assert len(constants.slot_hours) == 17 and sum(constants.slot_hours) == 7 * 2 + 12 + 5 * 2 + 12
    jack, jill = constants.workers[:2]
    assert jack.availability == 24 - 2           # 04:00-06:00
    assert jill.availability == 24               # away only on the 3rd, after the period
    assert jack.likes == frozenset({1}) and constants.workers[2].dislikes == frozenset({0, 1})
    # the load blends hours and shifts, but keeps the total: the average slot's load is its hours (ADR 0026)
    assert sum(constants.slot_load) == pytest.approx(sum(constants.slot_hours))
    # the flat units (ADR 0032): one average slot for an average worker, and the mean worst deficit
    mean_availability = sum(worker.availability for worker in constants.workers) / len(constants.workers)
    mean_load = sum(constants.slot_load) / len(constants.slot_load)
    assert constants.workload_unit == pytest.approx(mean_load ** 2 / mean_availability)
    assert constants.rest_unit == pytest.approx(rest_unit(constants.workers))


def test_pair_values_are_both_workers_like_values_of_each_other() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    neutral = constants.parameters.neutral_partner
    count = len(constants.workers)
    for worker, partner in itertools.product(range(count), repeat=2):  # the same worker twice included
        assert constants.pair_values[worker][partner] == (like_value(constants.workers[worker], partner, neutral)
                                                          + like_value(constants.workers[partner], worker, neutral))
    # Jack likes Jill and is neutral to Jeff, who dislikes him
    assert constants.pair_values[0][2] == neutral + DISLIKED_PARTNER
    assert like_value(constants.workers[0], 1, neutral) == LIKED_PARTNER


def test_workers_with_no_availability_or_deficit_are_left_out_of_the_units() -> None:
    period = span(0, 8)
    post = Post("desk", ShiftRules(dt.timedelta(hours=4), (("any", 1),)))
    away = Worker("Bob", unavailable=(span(0, 8),))
    schedule_input = ScheduleInput(Settings(period, dt.timedelta(hours=4)), (Worker("Anne"), away), (post,))
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    anne, bob = constants.workers
    assert bob.availability == 0 and bob.worst_deficit == 0
    assert constants.workload_unit == 4 ** 2 / 8          # Bob's availability doesn't count
    assert anne.worst_deficit == 0 and constants.rest_unit == 0  # 0-4 and 4-8 can't both be hers
    assert constants.shared_slots == 0
    assert workload_unit(constants.workers, [], 2) == 0


def test_a_slots_load_blends_its_hours_and_one_average_slot() -> None:
    assert slot_load(1, 3, 0) == 1      # hours only
    assert slot_load(1, 3, 1) == 3      # every shift counts as one average shift
    assert slot_load(1, 3, 0.5) == 2


def test_slots_of_the_same_load_share_a_load_class() -> None:
    # ADR 0040: the distinct loads, ascending, and each slot's index among them
    assert load_classes([2.5, 1.0, 2.5, 4.0]) == ((1.0, 2.5, 4.0), (1, 0, 1, 2))
    assert load_classes([]) == ((), ())
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    assert len(constants.load_classes) == len(set(constants.slot_hours))  # one class per slot length
    assert [constants.load_classes[index] for index in constants.slot_load_class] == list(constants.slot_load)
