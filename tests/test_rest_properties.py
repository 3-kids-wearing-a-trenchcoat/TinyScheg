"""
Provable properties of the rest part (ADR 0036), on small hand-built legal schedules. In each pair compared, every
worker has the same shifts of each post, so the workload and likes parts are equal and only rest differs; the
schedule that rests its workers worse must cost more.
"""
import datetime as dt

import pytest

from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_best_schedule
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import PreviousSchedule, ScheduleInput, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.scoring.constants import build_constants
from tinyscheg.scoring.penalty import Penalty, score
from tinyscheg.timing.datetime_range import DateTimeRange

START = dt.datetime(2025, 1, 1)
PATROLS = ["P1", "P2", "P3"]
TWO_HOUR_GATE_AND_PATROL = (("gate", 2), ("patrol", 8))


def span(start: float, end: float) -> DateTimeRange:
    """Hours from START."""
    return DateTimeRange(START + dt.timedelta(hours=start), START + dt.timedelta(hours=end))


def penalties(names: list[str], posts: tuple[tuple[str, float], ...], period: float, min_rest: float,
              *schedules: dict[str, list[str] | str],
              away: dict[str, tuple[float, float]] | None = None) -> list[Penalty]:
    """
    Score schedules of one input, each checked legal first
    :param names: the workers' names, available throughout unless away
    :param posts: (name, shift length in hours) of each post, one worker per shift
    :param period: the schedule's length in hours, from START
    :param min_rest: the minimum rest in hours
    :param schedules: each a mapping from a post to its shifts' workers in time order (a string of one-letter names)
    :param away: for some workers, the (start, end) hours they're unavailable
    :return: each schedule's penalty
    """
    away = away or {}
    schedule_input = ScheduleInput(Settings(span(0, period), dt.timedelta(hours=min_rest)),
                                   tuple(Worker(name, unavailable=(span(*away[name]),) if name in away else ())
                                         for name in names),
                                   tuple(Post(post, ShiftRules(dt.timedelta(hours=length), (("any", 1),)))
                                         for post, length in posts))
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    result = []
    for schedule in schedules:
        queues = {post: list(workers) for post, workers in schedule.items()}
        assignment = [names.index(queues[problem.shifts[slot.shift_index].post.name].pop(0)) for slot in problem.slots]
        assert hard_constraint_violations(schedule_input, problem.slots, assignment) == []
        result.append(score(constants, assignment))
    return result


def assert_only_rest_is_worse(better: Penalty, worse: Penalty) -> None:
    """The two differ in rest alone, and the second rests its workers worse."""
    assert worse.workload == pytest.approx(better.workload) and worse.likes == pytest.approx(better.likes)
    assert worse.rest > better.rest


@pytest.mark.parametrize("names, length, period, min_rest, better, worse", [
    # 2-hour shifts, 6 hours' minimum rest: all resting 10 hours beats four of them resting 6 (silent before)
    (list("ABCDEF"), 2, 24, 6, "ABCDEFABCDEF", "ABCDABEFCDEF"),
    # 3-hour shifts: all resting 12 hours beats four resting 6
    (list("ABCDE"), 3, 30, 6, "ABCDEABCDE", "ABCABDECDE"),
    # a minimum rest of 0: even 4-hour rests beat 2-hour ones
    (list("ABC"), 2, 18, 0, "ABCABCABC", "ABACBCACB"),
    # a loose schedule: all resting 15 hours, the norm, beats two resting 9 (silent before)
    (list("ABCDEF"), 3, 36, 6, "ABCDEFABCDEF", "ABCDAFEBCDEF"),
    # office-like: 8-hour shifts round the clock: all resting 24 hours beats one resting 8
    (list("ABCD"), 8, 72, 8, "ABCDABCDA", "ABCDADBCA"),
    # very short: 30-minute shifts, minimum rest 0: even 1-hour rests beat half-hour ones
    (list("ABC"), 0.5, 6, 0, "ABCABCABCABC", "ABACBCABCABC"),
])
def test_spread_out_rests_beat_crammed_ones(names: list[str], length: float, period: float, min_rest: float,
                                            better: str, worse: str) -> None:
    assert_only_rest_is_worse(*penalties(names, (("post", length),), period, min_rest, {"post": better},
                                         {"post": worse}))


def test_a_short_post_isnt_silenced_by_a_long_one() -> None:
    # a 2-hour gate and an 8-hour patrol: gate workers resting 10 hours beat two of them resting 6
    better, worse = penalties(PATROLS + list("ABCDEF"), TWO_HOUR_GATE_AND_PATROL, 24, 6,
                              {"gate": "ABCDEFABCDEF", "patrol": PATROLS}, {"gate": "ABCDAFEBCDEF", "patrol": PATROLS})
    assert_only_rest_is_worse(better, worse)


GATE_PAIRS = {0: "A", 4: "A", 1: "B", 5: "B", 2: "C", 8: "C", 3: "D", 9: "D", 6: "E", 11: "E"}


def gates(**extra: int) -> list[str]:
    """The gate's 12 shifts: the fixed pairs, plus each named worker's one shift."""
    by_shift = dict(GATE_PAIRS) | {index: name for name, index in extra.items()}
    return [by_shift[index] for index in range(12)]


def test_a_long_shift_earns_its_rest() -> None:
    # P1's gate shift 12 hours after their patrol beats one 6 hours after it
    better, worse = penalties(PATROLS + list("ABCDEG"), TWO_HOUR_GATE_AND_PATROL, 24, 6,
                              {"gate": gates(G=7, P1=10), "patrol": PATROLS},
                              {"gate": gates(P1=7, G=10), "patrol": PATROLS})
    assert_only_rest_is_worse(better, worse)


def test_the_same_two_shifts_cost_the_same_in_either_order() -> None:
    # P1 works the middle patrol and one gate shift, 6 hours before it or 6 hours after it
    pairs = {1: "A", 6: "A", 2: "B", 7: "B", 3: "C", 8: "C", 4: "D", 9: "D", 5: "E", 10: "E"}
    patrols = ["P2", "P1", "P3"]
    before, after = penalties(patrols + list("ABCDEG"), TWO_HOUR_GATE_AND_PATROL, 24, 6,
                              {"gate": [(pairs | {0: "P1", 11: "G"})[index] for index in range(12)], "patrol": patrols},
                              {"gate": [(pairs | {0: "G", 11: "P1"})[index] for index in range(12)], "patrol": patrols})
    assert before == after


def test_the_same_shortfall_costs_more_on_one_worker_than_on_two() -> None:
    # 3-hour shifts, 15 hours' rest the norm: 3 hours short on each of two workers beats 6 on one
    assert_only_rest_is_worse(*penalties(list("ABCDEF"), (("post", 3),), 36, 6, {"post": "ABCDEFABCEFD"},
                                         {"post": "ABCDEFCABDEF"}))


def test_unavailable_time_is_neither_work_nor_rest() -> None:
    # ADR 0038: 2-hour shifts over 24 hours; B is away from 06:00 to 18:00. B's shifts right before and right after
    # the absence (12 hours apart on the clock, none of it available) are crammed; at 00:00 and 22:00 (20 hours on the
    # clock, 8 available) they're spread out, although C, who swaps with B, then rests 12 hours rather than 20.
    # Counting the absence as rest, the two would cost the same.
    better, worse = penalties(list("ABCDEF"), (("post", 2),), 24, 2, {"post": "BACDEAFDECFB"},
                              {"post": "CABDEAFDEBFC"}, away={"B": (6, 18)})
    assert_only_rest_is_worse(better, worse)


def test_a_worker_idle_in_the_history_makes_up_for_it() -> None:
    # Anne and Bob took turns over 12 hours of history at the minimum rest, Cy did nothing; the next 12 hours give Cy
    # more than anyone, though that means cramming Cy at the minimum too
    post = Post("desk", ShiftRules(dt.timedelta(hours=2), (("any", 1),)))
    workers = tuple(Worker(name) for name in ("Anne", "Bob", "Cy"))

    def two_hourly(start: int, end: int, history: tuple[PreviousSchedule, ...] = ()) -> ScheduleInput:
        return ScheduleInput(Settings(span(start, end), dt.timedelta(hours=2)), workers, (post,), history)

    now = two_hourly(12, 24, (PreviousSchedule("before", two_hourly(0, 12), (0, 1) * 3),))
    problem = build_problem(now)
    constants = build_constants(problem.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    new = find_best_schedule(problem, constants).assignment[6:]
    assert new.count(2) > max(new.count(0), new.count(1))
