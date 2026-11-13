"""Tests for tools/audit.py, on hand-built schedules with known complaints."""
import datetime as dt
import pathlib

import pytest

from audit import (ANY_DAY, EXIT_ILLEGAL, EXIT_SUCCESS, LIKED_PARTNERS, LOAD, MAX_CHANGES, SHORT_STRAWS, WHOLE_PERIOD,
                   Audit, AuditContext, Baseline, Complaint, WorkerStats,
                   available_hours, build_context, candidate_changes, day_windows, evaluate, find_fixes, is_harmless,
                   is_legal_change, is_peer, main, slots_by_worker, summarize, with_history)
from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import PreviousSchedule, ScheduleInput, Settings
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


def mixed_lengths_context(period_hours: int) -> AuditContext:
    """Anne, Bob and Cy, a gate post of 4-hour shifts and a desk post of 12-hour shifts, from the start of 2025."""
    settings = Settings(DateTimeRange(START, at(period_hours)))
    posts = (Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),))),
             Post("desk", ShiftRules(dt.timedelta(hours=12), (("any", 1),))))
    schedule_input = ScheduleInput(settings, (Worker("Anne"), Worker("Bob"), Worker("Cy")), posts)
    shifts = generate_shifts(posts, settings.period)
    return build_context(schedule_input, shifts, all_slots(shifts))


def test_load_is_more_only_by_one_measure_and_no_less_by_the_other() -> None:
    # over 12 hours, stable order: gate 0-4 (Cy), desk 0-12 (Bob), gate 4-8 and 8-12 (Anne)
    context = mixed_lengths_context(12)
    # Bob's one 12-hour shift is 8 hours more than Cy's one 4-hour shift, with as many shifts; but Bob's only shift is
    # longer than the gap, so giving it to Cy wouldn't narrow it: within the tolerance. Anne's two shifts (8 hours)
    # against Bob's one (12 hours) is more shifts but fewer hours: without an exchange rate between the two, neither
    # did more, so neither complains; Anne against Cy, one shift and 4 hours (one of her shifts) more, is tolerated
    audit = evaluate(context, (2, 1, 0, 0))
    assert complaints_of(audit, LOAD) == []
    assert audit.stats[1].shortest_held[WHOLE_PERIOD] == 12


def test_an_hours_gap_counts_in_the_workers_own_shortest_shift() -> None:
    # over 24 hours: Anne has the desk 0-12 and the gate 12-16, 16 hours in 2 shifts; Bob has the gate 0-4 and 4-8,
    # 8 hours in 2 shifts. Anne's 4-hour shift could go to Bob and narrow the 8-hour gap: 8 / 4 = 2, a complaint
    context = mixed_lengths_context(24)
    owners = {("desk", at(0)): 0, ("gate", at(12)): 0, ("gate", at(0)): 1, ("gate", at(4)): 1}  # Cy has the rest
    assignment = tuple(owners.get((context.shifts[slot.shift_index].post.name, slot.time.start), 2)
                       for slot in context.slots)
    assert (0, 1, WHOLE_PERIOD, 1) in complaints_of(evaluate(context, assignment), LOAD)


def test_a_shift_counts_in_every_window_it_overlaps_with_the_hours_inside_it() -> None:
    # over 48 hours, the desk shift 12:00-24:00 started before the window from 16:00, and still counts in it, with
    # the 8 of its hours inside; it doesn't overlap the window from 24:00 at all
    context = mixed_lengths_context(48)
    desk = next(index for index, shift in enumerate(context.shifts)
                if shift.post.name == "desk" and shift.time.start == at(12))
    overlap = dict(zip(context.shift_windows[desk], context.shift_overlap[desk]))
    assert overlap["2025-01-01 04:00"] == 12 and overlap["2025-01-01 16:00"] == 8
    assert "2025-01-02 00:00" not in overlap and overlap[WHOLE_PERIOD] == 12


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
    before = Baseline({complaint.key: complaint.severity}, (), 6.0)
    assert is_harmless(before, Audit((), ()))
    assert is_harmless(before, Audit((), (complaint,)))
    assert not is_harmless(before, Audit((), (Complaint(LOAD, 0, 1, WHOLE_PERIOD, 3),)))      # more severe
    assert not is_harmless(before, Audit((), (Complaint(LOAD, 1, 0, WHOLE_PERIOD, 2),)))      # new


def straws_only(short_rests: int) -> WorkerStats:
    """A worker's statistics with nothing but the given number of short rests."""
    return WorkerStats((), {}, {}, {}, (), {}, 0, 0, {"short rest": short_rests, "disliked partner": 0})


def test_a_change_that_gives_anyone_a_new_short_straw_is_not_harmless() -> None:
    # even when the straw stays within the tolerance, so that nobody complains
    before = Baseline({}, ({"short rest": 0, "disliked partner": 0},) * 2, 6.0)
    assert is_harmless(before, Audit((straws_only(0), straws_only(0)), ()))
    assert not is_harmless(before, Audit((straws_only(1), straws_only(0)), ()))


def test_changes_are_judged_by_the_audited_schedules_norm() -> None:
    # everyone rests 8 hours: the norm makes nothing short (8 - 2 = 6), but against a norm of 9 every rest is short
    workers = [Worker(name) for name in ("Anne", "Bob", "Cy", "Dan", "Eve", "Fay")]
    context = context_for(workers, {"gate": {"any": 1}}, 48)
    assignment = (0, 1, 2) * 4
    own_norm = evaluate(context, assignment)
    assert own_norm.short_rest == 6 and all(stats.straws["short rest"] == 0 for stats in own_norm.stats)
    against_nine = evaluate(context, assignment, short_rest=9)
    assert against_nine.short_rest == 9 and against_nine.stats[0].straws["short rest"] == 3


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


# --- with a history (ADR 0031) ---

def history_input(new_workers: tuple[str, ...] = ("Anne", "Bob", "Cy")) -> ScheduleInput:
    """
    4-hour gate shifts with no minimum rest: a history over hours 0-24 in which Anne took four shifts, Bob two and
    Cy none, then a new period over hours 24-48
    """
    no_rest = dt.timedelta(0)
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),)))
    then = ScheduleInput(Settings(DateTimeRange(at(0), at(24)), no_rest),
                         (Worker("Anne"), Worker("Bob"), Worker("Cy")), (post,))
    previous = PreviousSchedule("day1.yml", then, (0, 1, 0, 1, 0, 0))
    return ScheduleInput(Settings(DateTimeRange(at(24), at(48)), no_rest), tuple(Worker(name) for name in new_workers),
                         (post,), (previous,))


def test_a_schedule_is_audited_together_with_its_history() -> None:
    schedule_input = history_input()
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    new = (0, 1, 2, 0, 1, 2)  # even on its own
    context, assignment = with_history(schedule_input, shifts, new)
    assert context.fixed_slots == 6 and assignment == (0, 1, 0, 1, 0, 0) + new
    assert context.availability[2][WHOLE_PERIOD] == 48
    audit = evaluate(context, assignment)
    # Anne's 6 shifts against Cy's 2 overall: the history's imbalance, which the new period could have made up for
    assert (0, 2, WHOLE_PERIOD, 3) in complaints_of(audit, LOAD)
    fixes = find_fixes(context, assignment, audit)
    assert fixes and all(slot >= context.fixed_slots for fix in fixes.values() for change in fix.changes
                         for slot in change.changed_slots)  # no fix changes the history


def test_a_worker_who_joined_was_unavailable_during_the_history() -> None:
    schedule_input = history_input(("Anne", "Bob", "Cy", "Dana"))
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    context, _ = with_history(schedule_input, shifts, (0, 1, 2, 3, 0, 1))
    assert context.availability[3][WHOLE_PERIOD] == 24
    assert not is_peer(context, 0, 3, WHOLE_PERIOD)  # Dana was around half as long, so Anne has no complaint
