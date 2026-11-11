"""Tests for tools/audit.py, on hand-built schedules with known complaints."""
import datetime as dt
import pathlib

import pytest

from audit import (EXIT_ILLEGAL, EXIT_SUCCESS, LOAD, SHORT_STRAWS, WHOLE_PERIOD, Audit, AuditContext, Complaint,
                   available_hours, build_context, days, evaluate, find_fixes, is_harmless, main, summarize)
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, Settings
from tinyscheg.model.shift_generation import all_slots, generate_shifts
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


def context_for(workers: list[Worker], posts: dict[str, dict[str, int]], period_hours: int, length: int = 4,
                min_rest: int = 0) -> AuditContext:
    """The audit context of an input with the given posts (name: roles), all with shifts of `length` hours."""
    settings = Settings(DateTimeRange(START, at(period_hours)), dt.timedelta(hours=min_rest))
    post_list = tuple(Post(name, ShiftRules(dt.timedelta(hours=length), tuple(roles.items())))
                      for name, roles in posts.items())
    schedule_input = ScheduleInput(settings, tuple(workers), post_list)
    shifts = generate_shifts(post_list, settings.period)
    return build_context(schedule_input, shifts, all_slots(shifts))


def complaints_of(audit: Audit, kind: str) -> list[tuple[int, int, str, float]]:
    """The complaints of one kind, as (worker, against, window, severity)."""
    return [(c.worker, c.against, c.window, c.severity) for c in audit.complaints if c.kind == kind]


# --- windows and availability ---

def test_days_start_at_the_boundary_and_a_shift_belongs_to_the_day_it_starts() -> None:
    period = DateTimeRange(at(6), at(30))
    assert [window.label for window in days(period)] == ["2025-01-01", "2025-01-02"]
    context = context_for([Worker("Anne")], {"gate": {"any": 1}}, 28)  # the last shift starts at 24:00
    assert context.shift_day[-2:] == ("2025-01-01", "2025-01-02")


def test_overlapping_unavailability_is_counted_once() -> None:
    away = (DateTimeRange(at(0), at(4)), DateTimeRange(at(2), at(6)))
    assert available_hours(away, DateTimeRange(at(0), at(24)), DateTimeRange(at(0), at(12))) == 6


# --- load ---

def test_one_extra_shift_is_tolerated_two_are_a_complaint() -> None:
    context = context_for([Worker("Anne"), Worker("Bob")], {"gate": {"any": 1}}, 20)  # 5 shifts
    assert complaints_of(evaluate(context, (0, 0, 0, 1, 1)), LOAD) == []
    context = context_for([Worker("Anne"), Worker("Bob")], {"gate": {"any": 1}}, 24)  # 6 shifts
    assert complaints_of(evaluate(context, (0, 0, 0, 0, 1, 1)), LOAD) == [
        (0, 1, "2025-01-01", 1), (0, 1, WHOLE_PERIOD, 1)]


def test_hours_count_in_units_of_the_longest_shift() -> None:
    # a 4-hour post and a 12-hour post over 12 hours: Bob's one 12-hour shift is 8 hours more than Cy's one 4-hour
    # shift, but less than one longest shift's worth, so the gap is 8 / 12, within the tolerance
    settings = Settings(DateTimeRange(START, at(12)))
    posts = (Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),))),
             Post("desk", ShiftRules(dt.timedelta(hours=12), (("any", 1),))))
    schedule_input = ScheduleInput(settings, (Worker("Anne"), Worker("Bob"), Worker("Cy")), posts)
    shifts = generate_shifts(posts, settings.period)
    context = build_context(schedule_input, shifts, all_slots(shifts))
    assert context.longest[WHOLE_PERIOD] == 12
    # stable order: gate 0-4 (Cy), desk 0-12 (Bob), gate 4-8 and 8-12 (Anne)
    assert complaints_of(evaluate(context, (2, 1, 0, 0)), LOAD) == []


def test_a_worker_who_was_away_longer_is_not_a_peer() -> None:
    bob = Worker("Bob", unavailable=(DateTimeRange(at(0), at(12)),))
    context = context_for([Worker("Anne"), bob], {"gate": {"any": 1}}, 24)
    assert complaints_of(evaluate(context, (0, 0, 0, 0, 1, 1)), LOAD) == []


# --- short straws and pairings ---

def test_short_straws_are_counted_by_kind() -> None:
    # Anne works 0-4 and 4-8 (no rest, a short straw) and has the heaviest day; Bob works 8-12
    context = context_for([Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob")], {"gate": {"any": 1}}, 12)
    stats = evaluate(context, (0, 0, 1)).stats
    assert stats[0].straws == {"short rest": 1, "heaviest day": 1, "disliked partner": 0}
    assert stats[1].total_straws == 0


def test_a_disliked_pairing_fixed_by_swapping_posts_in_the_same_hour_is_avoidable() -> None:
    # two posts of two, two 4-hour blocks; Anne is with Bob, whom she dislikes, both times
    workers = [Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob"), Worker("Cy"), Worker("Dan")]
    context = context_for(workers, {"gate": {"any": 2}, "desk": {"any": 2}}, 8)
    assignment = (0, 1, 2, 3, 0, 1, 2, 3)
    audit = evaluate(context, assignment)
    assert audit.stats[0].straws["disliked partner"] == 2
    straws = complaints_of(audit, SHORT_STRAWS)
    assert straws and all(worker == 0 for worker, *_ in straws)
    fixes = find_fixes(context, assignment, audit)
    assert all(fixes[c.key].description.startswith("swapping") for c in audit.complaints if c.kind == SHORT_STRAWS)


# --- avoidability ---

def test_extra_load_a_move_can_fix_is_avoidable() -> None:
    context = context_for([Worker("Anne"), Worker("Bob")], {"gate": {"any": 1}}, 24)
    assignment = (0, 0, 0, 0, 1, 1)
    audit = evaluate(context, assignment)
    fixes = find_fixes(context, assignment, audit)
    assert {c.key for c in audit.complaints if c.kind == LOAD} <= fixes.keys()
    assert summarize(audit, fixes).unavoidable_severity == 0


def test_extra_load_forced_by_roles_is_unavoidable() -> None:
    context = context_for([Worker("Anne", roles=frozenset({"medic"})), Worker("Bob")], {"aid": {"medic": 1}}, 16)
    assignment = (0, 0, 0, 0)
    audit = evaluate(context, assignment)
    assert complaints_of(audit, LOAD) == [(0, 1, "2025-01-01", 3), (0, 1, WHOLE_PERIOD, 3)]
    assert find_fixes(context, assignment, audit) == {}


def test_a_change_that_creates_or_worsens_a_complaint_is_not_harmless() -> None:
    complaint = Complaint(LOAD, 0, 1, WHOLE_PERIOD, 2)
    before = {complaint.key: complaint.severity}
    assert is_harmless(before, Audit((), ()))
    assert is_harmless(before, Audit((), (complaint,)))
    assert not is_harmless(before, Audit((), (Complaint(LOAD, 0, 1, WHOLE_PERIOD, 3),)))      # more severe
    assert not is_harmless(before, Audit((), (Complaint(LOAD, 1, 0, WHOLE_PERIOD, 2),)))      # new


# --- the summary and the command line ---

def test_concentration_is_the_most_aggrieved_workers_share() -> None:
    context = context_for([Worker("Anne", roles=frozenset({"medic"})), Worker("Bob")], {"aid": {"medic": 1}}, 16)
    audit = evaluate(context, (0, 0, 0, 0))
    summary = summarize(audit, {})
    assert summary.aggrieved == 1 and summary.concentration == 1
    assert summary.severity_by_worker[0][0] == 0


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
        assert captured.out.startswith(f"{schedule_input.workers[0].name}: ") and "concentration:" in captured.out
