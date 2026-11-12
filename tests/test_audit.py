"""Tests for tools/audit.py, on hand-built schedules with known complaints."""
import datetime as dt
import pathlib

import pytest

from audit import (ANY_DAY, EXIT_ILLEGAL, EXIT_SUCCESS, LIKED_PARTNERS, LOAD, MAX_CHANGES, SHORT_STRAWS, WHOLE_PERIOD,
                   Audit, AuditContext, Complaint,
                   available_hours, build_context, candidate_changes, day_windows, evaluate, find_fixes, is_harmless,
                   is_legal_change, main, slots_by_worker, summarize)
from schedule_checker import hard_constraint_violations
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

def test_day_windows_start_at_each_shift_and_lie_within_the_period() -> None:
    context = context_for([Worker("Anne")], {"gate": {"any": 1}}, 36)  # shifts start every 4 hours, 0 to 32
    assert [window.label for window in context.windows] == [
        "2025-01-01 00:00", "2025-01-01 04:00", "2025-01-01 08:00", "2025-01-01 12:00", WHOLE_PERIOD]
    assert context.shift_windows[3] == ("2025-01-01 00:00", "2025-01-01 04:00", "2025-01-01 08:00",
                                        "2025-01-01 12:00", WHOLE_PERIOD)  # starts at 12:00
    assert context.shift_windows[0] == ("2025-01-01 00:00", WHOLE_PERIOD)


def test_a_period_of_a_day_or_less_has_no_day_windows() -> None:
    assert day_windows(DateTimeRange(at(16), at(40)), ()) == []
    assert [window.label for window in context_for([Worker("Anne")], {"gate": {"any": 1}}, 24).windows] == [
        WHOLE_PERIOD]


def test_overlapping_unavailability_is_counted_once() -> None:
    away = (DateTimeRange(at(0), at(4)), DateTimeRange(at(2), at(6)))
    assert available_hours(away, DateTimeRange(at(0), at(24)), DateTimeRange(at(0), at(12))) == 6


# --- load ---

def test_one_extra_shift_is_tolerated_two_are_a_complaint() -> None:
    context = context_for([Worker("Anne"), Worker("Bob")], {"gate": {"any": 1}}, 20)  # 5 shifts
    assert complaints_of(evaluate(context, (0, 0, 0, 1, 1)), LOAD) == []
    context = context_for([Worker("Anne"), Worker("Bob")], {"gate": {"any": 1}}, 24)  # 6 shifts
    assert complaints_of(evaluate(context, (0, 0, 0, 0, 1, 1)), LOAD) == [(0, 1, WHOLE_PERIOD, 1)]


def test_a_day_is_any_24_hours_whatever_midnight_and_counts_once_per_pair() -> None:
    # 4-hour shifts over 36 hours; everyone works 3 shifts, but Anne's are 20:00-08:00 straight, across midnight,
    # and Cy's 08:00-20:00, while Bob has none between 08:00 and 08:00 the next day (windows from 08:00)
    context = context_for([Worker("Anne"), Worker("Bob"), Worker("Cy")], {"gate": {"any": 1}}, 36)
    audit = evaluate(context, (1, 1, 2, 2, 2, 0, 0, 0, 1))
    assert sorted(complaints_of(audit, LOAD)) == [(0, 1, ANY_DAY, 2), (2, 0, ANY_DAY, 1), (2, 1, ANY_DAY, 2)]


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
    # 4-hour shifts; the others rest 8 hours between shifts, Anne works 0-4 and 4-8 with no rest: a short straw
    workers = [Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob"), Worker("Cy"), Worker("Dan")]
    context = context_for(workers, {"gate": {"any": 1}}, 36)
    audit = evaluate(context, (0, 0, 1, 2, 3, 1, 2, 3, 1))
    assert audit.stats[0].straws == {"short rest": 1, "disliked partner": 0}
    assert all(stats.total_straws == 0 for stats in audit.stats[1:])
    # a gap of one straw is tolerated
    assert complaints_of(audit, SHORT_STRAWS) == []


def test_a_rest_is_short_only_against_the_schedules_own_norm() -> None:
    # the same 8-hour rests: short when the others rest 16-20 hours, not when everyone rests 8
    workers = [Worker(name) for name in ("Anne", "Bob", "Cy", "Dan", "Eve", "Fay")]
    context = context_for(workers, {"gate": {"any": 1}}, 48)
    # 12 shifts of 4 hours: Anne 0-4, 12-16, 24-28 (rests 8, 8); the others rest 16 or 20 hours, or work once
    long_rests = evaluate(context, (0, 1, 2, 0, 3, 4, 0, 1, 2, 3, 4, 5))
    assert long_rests.stats[0].rests == (8.0, 8.0)
    assert long_rests.stats[0].straws["short rest"] == 2
    complaints = complaints_of(long_rests, SHORT_STRAWS)
    assert complaints and all(worker == 0 for worker, *_ in complaints)  # 2 straws against 0
    everyone_eight = evaluate(context, (0, 1, 2) * 4)
    assert all(stats.straws["short rest"] == 0 for stats in everyone_eight.stats)


def test_a_disliked_pairing_has_an_easy_fix_by_swapping_posts_in_the_same_hour() -> None:
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


# --- easy fixes ---

def test_extra_load_a_move_can_fix_has_an_easy_fix() -> None:
    context = context_for([Worker("Anne"), Worker("Bob")], {"gate": {"any": 1}}, 24)
    assignment = (0, 0, 0, 0, 1, 1)
    audit = evaluate(context, assignment)
    fixes = find_fixes(context, assignment, audit)
    assert {c.key for c in audit.complaints if c.kind == LOAD} <= fixes.keys()
    assert summarize(audit, fixes).no_fix_severity == 0
    assert all(len(fix.changes) == 1 for fix in fixes.values())


def test_a_wide_gap_is_fixed_by_a_chain_of_changes() -> None:
    # Anne has all six shifts and Bob none: each move narrows the gap by two, so it takes three to remove it
    assert MAX_CHANGES >= 3
    context = context_for([Worker("Anne"), Worker("Bob")], {"gate": {"any": 1}}, 24)
    assignment = (0, 0, 0, 0, 0, 0)
    audit = evaluate(context, assignment)
    overall = next(c for c in audit.complaints if c.kind == LOAD and c.window == WHOLE_PERIOD)
    assert overall.severity == 5
    fix = find_fixes(context, assignment, audit)[overall.key]
    assert len(fix.changes) == 3 and all(change.description.startswith("giving Bob") for change in fix.changes)
    assert ", then " in fix.description


def test_extra_load_forced_by_roles_has_no_easy_fix() -> None:
    context = context_for([Worker("Anne", roles=frozenset({"medic"})), Worker("Bob")], {"aid": {"medic": 1}}, 16)
    assignment = (0, 0, 0, 0)
    audit = evaluate(context, assignment)
    assert complaints_of(audit, LOAD) == [(0, 1, WHOLE_PERIOD, 3)]
    assert find_fixes(context, assignment, audit) == {}


def test_a_change_that_creates_or_worsens_a_complaint_is_not_harmless() -> None:
    complaint = Complaint(LOAD, 0, 1, WHOLE_PERIOD, 2)
    before = {complaint.key: complaint.severity}
    assert is_harmless(before, Audit((), ()))
    assert is_harmless(before, Audit((), (complaint,)))
    assert not is_harmless(before, Audit((), (Complaint(LOAD, 0, 1, WHOLE_PERIOD, 3),)))      # more severe
    assert not is_harmless(before, Audit((), (Complaint(LOAD, 1, 0, WHOLE_PERIOD, 2),)))      # new


def test_the_quick_legality_check_agrees_with_the_full_checker() -> None:
    # every move and swap from the example's schedule, and from a legal schedule one change away from it
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    context = build_context(schedule_input, problem.shifts, problem.slots)

    def legal_changes(start: tuple[int, ...]) -> list[tuple[int, ...]]:
        """Check every change from a legal schedule both ways, and return the legal ones."""
        own_slots = slots_by_worker(start, len(schedule_input.workers))
        legal, illegal = [], 0
        for change in candidate_changes(context, start):
            expected = not hard_constraint_violations(schedule_input, problem.slots, change.assignment)
            assert is_legal_change(context, own_slots, change) == expected, change.description
            if expected:
                legal.append(change.assignment)
            else:
                illegal += 1
        assert legal and illegal
        return legal

    legal_changes(legal_changes(assignment)[0])


# --- the summary and the command line ---

def test_concentration_is_the_most_aggrieved_workers_share() -> None:
    context = context_for([Worker("Anne", roles=frozenset({"medic"})), Worker("Bob")], {"aid": {"medic": 1}}, 16)
    audit = evaluate(context, (0, 0, 0, 0))
    summary = summarize(audit, {})
    assert summary.aggrieved == 1 and summary.concentration == 1
    assert summary.severity_by_worker[0][0] == 0


def test_liked_partner_complaints_are_counted_apart_from_the_main_measures() -> None:
    # Cy and Dan like each other and share both shifts; Anne and Bob like each other and never share one
    workers = [Worker("Anne", likes=frozenset({"Bob"})), Worker("Bob", likes=frozenset({"Anne"})),
               Worker("Cy", likes=frozenset({"Dan"})), Worker("Dan", likes=frozenset({"Cy"})), Worker("Eve"),
               Worker("Fay")]
    context = context_for(workers, {"gate": {"any": 2}, "desk": {"any": 2}, "patrol": {"any": 2}}, 8)
    assignment = (2, 3, 0, 4, 1, 5) * 2  # gate: Cy and Dan; desk: Anne and Eve; patrol: Bob and Fay; twice
    audit = evaluate(context, assignment)
    liked = [c for c in audit.complaints if c.kind == LIKED_PARTNERS]
    assert liked
    summary = summarize(audit, find_fixes(context, assignment, audit))
    main = [c for c in audit.complaints if c.kind != LIKED_PARTNERS]
    assert summary.complaints == len(main)
    assert summary.easy_fix_severity + summary.no_fix_severity == pytest.approx(sum(c.severity for c in main))
    assert summary.separate_complaints == len(liked)
    assert summary.separate_severity == pytest.approx(sum(c.severity for c in liked))


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
