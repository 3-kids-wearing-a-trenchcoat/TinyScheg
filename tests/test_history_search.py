"""Tests for a schedule with a history (ADR 0031): one schedule, already filled up to the new period."""
import datetime as dt
from itertools import product

from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_best_schedule
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import PreviousSchedule, ScheduleInput, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.scoring.constants import ScoringConstants, build_constants
from tinyscheg.scoring.penalty import score
from tinyscheg.timing.datetime_range import DateTimeRange

DESK = Post("desk", ShiftRules(dt.timedelta(hours=4), (("any", 1),)))
MIN_REST = dt.timedelta(hours=4)
ANNE, BOB, CY = 0, 1, 2


def period(start: int, end: int) -> DateTimeRange:
    """Hours from the start of 2025."""
    begin = dt.datetime(2025, 1, 1)
    return DateTimeRange(begin + dt.timedelta(hours=start), begin + dt.timedelta(hours=end))


def schedule(start: int, end: int, workers: tuple[str, ...] = ("Anne", "Bob", "Cy"),
             history: tuple[PreviousSchedule, ...] = ()) -> ScheduleInput:
    """An input with one desk post of 4-hour shifts over the hours given."""
    return ScheduleInput(Settings(period(start, end), MIN_REST), tuple(Worker(name) for name in workers), (DESK,),
                         history)


def previous(start: int, end: int, assignment: tuple[int, ...],
             workers: tuple[str, ...] = ("Anne", "Bob", "Cy")) -> PreviousSchedule:
    """A previous schedule over the hours given, filled as given."""
    return PreviousSchedule(f"{start}-{end}", schedule(start, end, workers), assignment)


# Anne worked twice, the second time up to the new period's start; Bob once, Cy not at all
HISTORY = (previous(0, 12, (ANNE, BOB, ANNE)),)
NOW = schedule(12, 24, history=HISTORY)


def constants_for(schedule_input: ScheduleInput) -> ScoringConstants:
    """The scoring constants of the whole schedule."""
    problem = build_problem(schedule_input)
    assert problem.settings is not None
    return build_constants(problem.settings, problem.workers, problem.shifts, problem.slots, problem.scoring_domains)


def test_the_history_is_the_filled_first_part_of_one_schedule() -> None:
    problem = build_problem(NOW)
    assert problem.fixed == (ANNE, BOB, ANNE, None, None, None)
    assert [shift.time for shift in problem.new_shifts] == [period(12, 16), period(16, 20), period(20, 24)]
    assert [slot.index for slot in problem.new_slots] == [3, 4, 5]
    assert problem.settings is not None and problem.settings.period == period(0, 24)


def test_the_minimum_rest_holds_across_the_boundary() -> None:
    problem = build_problem(NOW)
    assert ANNE not in problem.domains[3]  # she worked until 12:00
    result = find_best_schedule(problem, constants_for(NOW))
    assert result.assignment is not None and result.assignment[3] != ANNE
    new = result.assignment[3:]
    assert hard_constraint_violations(NOW, problem.new_slots, new) == []
    assert hard_constraint_violations(NOW, problem.new_slots, (ANNE,) + new[1:]) != []  # the checker sees it too


def test_the_new_schedule_makes_up_for_the_history() -> None:
    # 2-hour shifts with 2 hours' minimum rest; Anne and Bob took turns over the history, Cy did nothing. Making up
    # for it crams Cy at the minimum rest, as Anne and Bob were; with each worker's shortfall squared (ADR 0036), their
    # further short rests cost more than Cy's first ones, so Cy still takes more
    post = Post("desk", ShiftRules(dt.timedelta(hours=2), (("any", 1),)))
    workers = tuple(Worker(name) for name in ("Anne", "Bob", "Cy"))

    def two_hourly(start: int, end: int, history: tuple[PreviousSchedule, ...] = ()) -> ScheduleInput:
        settings = Settings(period(start, end), dt.timedelta(hours=2))
        return ScheduleInput(settings, workers, (post,), history)

    history = (PreviousSchedule("before", two_hourly(0, 12), (ANNE, BOB) * 3),)
    without, now = two_hourly(12, 24), two_hourly(12, 24, history)
    alone = find_best_schedule(build_problem(without), constants_for(without)).assignment
    extended = find_best_schedule(build_problem(now), constants_for(now)).assignment
    assert alone is not None and extended is not None
    new = extended[6:]
    assert [alone.count(worker) for worker in (ANNE, BOB, CY)] == [2, 2, 2]  # without history, an even split
    assert new.count(CY) > 2 and new.count(CY) > max(new.count(ANNE), new.count(BOB))  # Cy makes up for it


def test_branch_and_bound_finds_the_best_completion() -> None:
    problem, constants = build_problem(NOW), constants_for(NOW)
    legal = [assignment for assignment in product(*problem.domains)
             if not hard_constraint_violations(NOW, problem.new_slots, assignment[3:])]
    lowest = min(score(constants, assignment).total for assignment in legal)
    result = find_best_schedule(problem, constants)
    assert result.penalty is not None and result.penalty.total == lowest
    assert result.assignment is not None and result.assignment[:3] == (ANNE, BOB, ANNE)


def test_incremental_scoring_starts_from_the_filled_history() -> None:
    problem, constants = build_problem(NOW), constants_for(NOW)
    incremental = find_best_schedule(problem, constants)
    from_scratch = find_best_schedule(problem, constants, incremental=False)
    assert incremental.penalty == from_scratch.penalty and incremental.nodes == from_scratch.nodes


def test_workers_who_joined_were_unavailable_and_gaps_count_for_no_one() -> None:
    # a 4-hour gap between the history and the new period; Dana joined for the new period, Cy has left
    history = (previous(0, 8, (0, 1), workers=("Anne", "Bob", "Cy")),)
    now = schedule(12, 24, workers=("Anne", "Bob", "Dana"), history=history)
    problem = build_problem(now)
    constants = constants_for(now)
    assert [worker.availability for worker in constants.workers] == [20, 20, 12]  # 8 + 12, without the gap
    assert problem.fixed[:2] == (0, 1) and len(problem.slots) == 2 + 3
    assert find_best_schedule(problem, constants).assignment is not None


def test_departed_workers_slots_are_dropped() -> None:
    history = (previous(0, 8, (2, 0), workers=("Anne", "Bob", "Cy")),)  # Cy, then Anne
    now = schedule(12, 24, workers=("Anne", "Bob"), history=history)
    assert build_problem(now).fixed[:1] == (0,)  # only Anne's shift is left of the history


# --- who could have filled a history slot (ADR 0037) ---

def test_a_history_slot_counts_for_everyone_who_could_have_filled_it() -> None:
    # Cy was away for the first history shift; Dan joined after the history. Each history slot counts for everyone
    # who was in that period's input and available for it, not only the worker who had it; new slots as usual.
    away = ScheduleInput(Settings(period(0, 12), MIN_REST),
                         (Worker("Anne"), Worker("Bob"), Worker("Cy", unavailable=(period(0, 4),))), (DESK,))
    now = schedule(12, 24, ("Anne", "Bob", "Cy", "Dan"), (PreviousSchedule("0-12", away, (ANNE, BOB, ANNE)),))
    problem = build_problem(now)
    assert problem.domains[:3] == ((ANNE,), (BOB,), (ANNE,))  # the search's: who did
    assert problem.scoring_domains[:3] == ((ANNE, BOB), (ANNE, BOB, CY), (ANNE, BOB, CY))  # the scoring's: who could
    assert problem.scoring_domains[3:] == ((0, 1, 2, 3),) * 3


def test_a_history_slot_counts_by_the_roles_of_its_own_period() -> None:
    # Cy became a supervisor after the history, so the history's supervisor shifts don't count for Cy
    supervising = Post("desk", ShiftRules(dt.timedelta(hours=4), (("supervisor", 1),)))
    supervisors = (Worker("Anne", roles=frozenset({"supervisor"})), Worker("Bob", roles=frozenset({"supervisor"})))
    then = ScheduleInput(Settings(period(0, 12), MIN_REST), supervisors + (Worker("Cy"),), (supervising,))
    now = ScheduleInput(Settings(period(12, 24), MIN_REST),
                        supervisors + (Worker("Cy", roles=frozenset({"supervisor"})),), (supervising,),
                        (PreviousSchedule("0-12", then, (ANNE, BOB, ANNE)),))
    problem = build_problem(now)
    assert problem.scoring_domains[:3] == ((ANNE, BOB),) * 3
    assert problem.scoring_domains[3:] == ((ANNE, BOB, CY),) * 3


def test_being_passed_over_in_the_history_doesnt_shrink_the_worst_rest_deficit() -> None:
    # Anne and Bob took turns over the history, Cy did nothing. From scratch, Cy could have been given those shifts
    # too, so Cy's worst possible deficit is the same as theirs, and an hour short costs Cy no more than them; before
    # ADR 0037 it was computed from the new period alone, making Cy's hours short the dearest of the three
    post = Post("desk", ShiftRules(dt.timedelta(hours=2), (("any", 1),)))
    workers = tuple(Worker(name) for name in ("Anne", "Bob", "Cy"))

    def two_hourly(start: int, end: int, history: tuple[PreviousSchedule, ...] = ()) -> ScheduleInput:
        return ScheduleInput(Settings(period(start, end), dt.timedelta(hours=2)), workers, (post,), history)

    now = two_hourly(12, 24, (PreviousSchedule("0-12", two_hourly(0, 12), (ANNE, BOB) * 3),))
    problem = build_problem(now)
    assert problem.settings is not None
    worst = [worker.worst_deficit for worker in constants_for(now).workers]
    assert worst[ANNE] == worst[BOB] == worst[CY] > 0
    passed_over = build_constants(problem.settings, problem.workers, problem.shifts, problem.slots, problem.domains)
    assert passed_over.workers[CY].worst_deficit < passed_over.workers[ANNE].worst_deficit  # what it was before
