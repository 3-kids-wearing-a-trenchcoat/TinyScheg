"""
Tests for tools/audit.py as a whole: availability, the fix search's legality against the full checker, a schedule
audited with its history, and the command line. Each decision has its own tests in test_audit_grievances.py,
test_audit_fixes.py and test_audit_report.py.
"""
import datetime as dt
import itertools
import pathlib

import pytest

from audit import (DISLIKED_PARTNER, EXIT_ILLEGAL, EXIT_SUCCESS, LOAD, MISSING_LIKE, REST, available_hours,
                   build_context, find_grievances, kind_measures, main, nearby_schedules, report_grievances,
                   with_history, worker_tallies)
from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import PreviousSchedule, ScheduleInput, Settings
from tinyscheg.model.shift_generation import generate_shifts
from tinyscheg.model.worker import Worker
from tinyscheg.output.csv_writer import write_csv
from tinyscheg.output.grid import build_grid
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.timing.datetime_range import DateTimeRange

START = dt.datetime(2025, 1, 1)
EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"


def at(hour: int) -> dt.datetime:
    """A moment, in hours from the start of 2025."""
    return START + dt.timedelta(hours=hour)


def test_overlapping_unavailability_is_counted_once() -> None:
    away = (DateTimeRange(at(0), at(4)), DateTimeRange(at(2), at(6)))
    assert available_hours(away, DateTimeRange(at(0), at(24)), DateTimeRange(at(0), at(12))) == 6


def test_the_schedules_one_change_away_are_exactly_the_legal_ones() -> None:
    # every move and swap from the example's first schedule, checked with the full hard-constraint checker: the
    # search's own legality check must give the same schedules (but for swaps within one shift, which it leaves out:
    # they change nobody's shifts or partners, so no grievance)
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    context = build_context(schedule_input, problem.shifts, problem.slots)
    workers = range(len(schedule_input.workers))
    candidates = set()
    for slot in range(len(assignment)):  # moves
        for worker in workers:
            if worker != assignment[slot]:
                candidates.add(assignment[:slot] + (worker,) + assignment[slot + 1:])
    shift_of = [slot.shift_index for slot in problem.slots]
    for first, second in itertools.combinations(range(len(assignment)), 2):  # swaps
        if assignment[first] != assignment[second] and shift_of[first] != shift_of[second]:
            swapped = list(assignment)
            swapped[first], swapped[second] = assignment[second], assignment[first]
            candidates.add(tuple(swapped))
    legal = {candidate for candidate in candidates
             if not hard_constraint_violations(schedule_input, problem.slots, candidate)}
    assert legal and legal != candidates
    assert {nearby for _, nearby in nearby_schedules(context, assignment, 1)} == legal


def history_input(new_workers: tuple[str, ...] = ("Anne", "Bob", "Cy")) -> ScheduleInput:
    """
    4-hour gate shifts with no minimum rest (but never back to back): a history over hours 0-24 in which Anne took
    three shifts, Bob two and Cy one, then a new period over hours 24-48
    """
    no_rest = dt.timedelta(0)
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),)))
    then = ScheduleInput(Settings(DateTimeRange(at(0), at(24)), no_rest),
                         (Worker("Anne"), Worker("Bob"), Worker("Cy")), (post,))
    previous = PreviousSchedule("day1.yml", then, (0, 1, 0, 1, 0, 2))
    return ScheduleInput(Settings(DateTimeRange(at(24), at(48)), no_rest), tuple(Worker(name) for name in new_workers),
                         (post,), (previous,))


def test_a_schedule_is_audited_together_with_its_history() -> None:
    schedule_input = history_input()
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    new = (0, 2, 0, 2, 0, 1)  # Anne works every other shift again
    context, assignment = with_history(schedule_input, shifts, new)
    assert context.fixed_slots == 6 and assignment == (0, 1, 0, 1, 0, 2) + new
    assert context.staffed_availability == (48, 48, 48)
    # Anne's 6 shifts over both periods against a share of 4 (16 hours): the new period added to the history's
    # imbalance instead of making up for it
    load = find_grievances(context, assignment).load[0]
    assert load is not None and (load.events, load.extra_hours, load.share) == (2, 8.0, 16.0)


def test_a_worker_who_joined_later_has_a_smaller_share() -> None:
    # Dana joined for the new period, so she was available half as long as the others: her share of the 48 hours is
    # 48 * 24 / 168, the others' 48 * 48 / 168. Anne's 20 hours over both periods are 6.29 above hers (2 of her
    # shifts), Bob's 16 are 2.29 above (1), and Dana's 4 are below hers
    schedule_input = history_input(("Anne", "Bob", "Cy", "Dana"))
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    context, assignment = with_history(schedule_input, shifts, (0, 1, 0, 1, 2, 3))
    assert context.staffed_availability == (48, 48, 48, 24)
    load = find_grievances(context, assignment).load
    assert [g.events if g else 0 for g in load] == [2, 1, 0, 0]
    assert load[0] is not None and load[0].share == pytest.approx(48 * 48 / 168)


def test_the_measures_per_kind_follow_the_closing_table() -> None:
    # Anne: 20 hours over both periods against a share of 16 (1 of her 4-hour shifts), with a harmless fix; and three
    # 4-hour rests after 4-hour shifts, where the typical rest is 2 hours per hour of the shift before (8 hours): two
    # wholly in the history, the third with a harmless fix. Bob: one such rest, in the history. Events wholly in the
    # history are counted, but never as having a harmless fix
    schedule_input = history_input()
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    context, assignment = with_history(schedule_input, shifts, (0, 1, 2, 0, 1, 2))
    tallies = worker_tallies(context, assignment, report_grievances(context, assignment))
    assert [tallied.name for tallied in tallies] == ["Anne", "Bob", "Cy"]
    assert [(tallied.hours[REST], tallied.hours_harmless[REST]) for tallied in tallies] == [(12, 4), (4, 0), (0, 0)]
    assert [(tallied.hours[LOAD], tallied.hours_harmless[LOAD]) for tallied in tallies] == [(4, 4), (0, 0), (0, 0)]
    measures = kind_measures(tallies)
    assert measures[LOAD] == {"harmless": 1, "most": 1, "events": 1, "hours_harmless": 4, "hours_most": 4, "hours": 4}
    assert measures[REST] == {"harmless": 1, "most": 3, "events": 4, "hours_harmless": 4, "hours_most": 12,
                              "hours": 16}
    assert measures[DISLIKED_PARTNER] == measures[MISSING_LIKE] == {"harmless": 0, "most": 0, "events": 0}


@pytest.mark.parametrize("illegal", [False, True])
def test_command_line(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], illegal: bool) -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    if illegal:  # the first worker in two slots of the same shift
        first_shared = next(shift for shift in problem.shifts if len(shift.slots) > 1)
        assignment = tuple(assignment[0] if slot.shift_index == first_shared.index else worker
                           for slot, worker in zip(problem.slots, assignment))
    path = tmp_path / "schedule.csv"
    write_csv(build_grid(schedule_input.posts, problem.shifts, problem.workers, assignment), path)
    assert main([str(EXAMPLE_INPUT), str(path)]) == (EXIT_ILLEGAL if illegal else EXIT_SUCCESS)
    captured = capsys.readouterr()
    if illegal:
        assert "breaks hard constraints" in captured.err
    else:
        assert captured.out.startswith("fixes searched up to 3 changes\n\n"
                                       f"{schedule_input.workers[0].name}: ") and "events by kind" in captured.out
