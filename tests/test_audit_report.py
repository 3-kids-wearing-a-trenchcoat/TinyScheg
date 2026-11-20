"""Tests for the audit's report (tools/audit.py, ADR 0048): the cards, the closing table, the JSON and the options."""
import datetime as dt
import json
import pathlib

import pytest

from audit import (DISLIKED_PARTNER, EXIT_SUCCESS, KIND_ORDER, report_grievances, report_json, report_text, main,
                   tally, with_history, workers_by_shift)
from test_audit_fixes import ANNE, BOB, CY, at, trade_context
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

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"
TRADE = (ANNE, BOB, CY, ANNE, BOB, CY)  # Anne and Bob share 0-2 and 8-10; Cy has 4-6 and 12-14


def test_a_card_shows_each_grievance_with_its_events_and_fix() -> None:
    context = trade_context()
    text = report_text(context, TRADE, report_grievances(context, TRADE))
    assert text.startswith("fixes searched up to 3 changes\n\nAnne: 2 shifts, 4 h; available 8 h (of 8 h with a "
                           "post staffed)")
    card = text.split("\n\n")[1]
    assert "  rests: 6 h\n  partners: Bob ×2; liked pairings: 0\n  grievances:\n" in card
    assert "    - disliked partner: Bob, in 2 shifts\n" in card
    assert "      harmless fix (2 changes, removes 2 events): swap " in card
    assert "Cy: 2 shifts, 4 h; available 8 h (of 8 h with a post staffed)\n  rests: 6 h\n  partners: none; liked " \
           "pairings: 0\n  grievances: none" in text


def test_the_closing_table_counts_events_by_kind_and_never_adds_kinds() -> None:
    context = trade_context()
    report = report_grievances(context, TRADE)
    counts = tally(context, workers_by_shift(context, TRADE), report)
    assert counts[ANNE][DISLIKED_PARTNER] == {"events": 2, "harmless": 2, "transfers": 0, "none": 0, "history": 0}
    assert all(cell["events"] == 0 for worker in (BOB, CY) for cell in counts[worker].values())
    table = report_text(context, TRADE, report).split("\n\n")[-1].splitlines()
    assert table[0] == ("events by kind (with a harmless fix / only transfers / no fix of up to 3 changes / in the "
                        "history)")
    assert table[1].split() == list(" ".join(KIND_ORDER).split())
    assert table[2].split() == ["Anne", "0", "0", "2", "(2/0/0/0)", "0"]


def test_with_the_search_off_the_report_claims_nothing_about_fixes() -> None:
    context = trade_context()
    text = report_text(context, TRADE, report_grievances(context, TRADE, max_changes=0))
    assert text.startswith("fix search off\n") and "fix" not in text.split("\n\n", 1)[1]
    assert text.splitlines()[-3].split() == ["Anne", "0", "0", "2", "0"]


def test_an_event_in_the_history_says_no_change_can_reach_it() -> None:
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 2),)))
    workers = (Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob"), Worker("Cy"), Worker("Dana"))
    then = ScheduleInput(Settings(DateTimeRange(at(0), at(4)), dt.timedelta(0)), workers, (post,))
    schedule_input = ScheduleInput(Settings(DateTimeRange(at(8), at(16)), dt.timedelta(0)), workers, (post,),
                                   (PreviousSchedule("day1.yml", then, (ANNE, BOB)),))
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    context, assignment = with_history(schedule_input, shifts, (ANNE, CY, BOB, 3))  # apart in the new period
    text = report_text(context, assignment, report_grievances(context, assignment))
    assert ("    - disliked partner: Bob, in 1 shift\n        gate 2025-01-01 00:00–04:00 (in the history)\n"
            "      in the history: no change can reach it") in text


def test_the_json_report_has_the_same_content_and_the_reach() -> None:
    context = trade_context()
    data = report_json(context, TRADE, report_grievances(context, TRADE))
    assert json.loads(json.dumps(data)) == data
    assert data["max_changes"] == 3 and [worker["name"] for worker in data["workers"]] == ["Anne", "Bob", "Cy"]
    grievance, = data["workers"][ANNE]["grievances"]
    assert grievance["kind"] == DISLIKED_PARTNER and grievance["person"] == "Bob" and grievance["events"] == 2
    assert grievance["harmless"]["size"] == 2 and grievance["harmless"]["creates"] == []
    assert data["workers"][ANNE]["counts"][DISLIKED_PARTNER]["harmless"] == 2


def example_schedule_file(tmp_path: pathlib.Path) -> pathlib.Path:
    """The example's first legal schedule, written as CSV."""
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    path = tmp_path / "schedule.csv"
    write_csv(build_grid(schedule_input.posts, problem.shifts, problem.workers, assignment), path)
    return path


def test_the_command_line_options(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = example_schedule_file(tmp_path)
    assert main([str(EXAMPLE_INPUT), str(path), "--max-changes", "1", "--json"]) == EXIT_SUCCESS
    data = json.loads(capsys.readouterr().out)
    assert data["max_changes"] == 1 and data["history_schedules"] == 0
    assert main([str(EXAMPLE_INPUT), str(path), "--max-changes", "0"]) == EXIT_SUCCESS
    assert capsys.readouterr().out.startswith("fix search off\n")
    with pytest.raises(SystemExit):
        main([str(EXAMPLE_INPUT), str(path), "--max-changes", "-1"])
    assert "must be at least 0" in capsys.readouterr().err
