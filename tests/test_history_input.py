"""Tests for the history input section (ADR 0029): reading previous schedules, validating them, and warnings."""
import pathlib
import textwrap

import pytest

from audit import main as audit_main
from schedule_checker import hard_constraint_violations
from tinyscheg.cli import EXIT_SUCCESS, main
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.output.grid import build_grid
from tinyscheg.output.writers import write_schedule
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.schedule_reader import read_schedule
from tinyscheg.parsing.validation import InputError, history_warnings


def input_text(start: str, end: str, workers: tuple[str, ...] = ("Anne", "Bob", "Cy"), length: int = 4,
               history: str = "") -> str:
    """An input with one desk post of shifts of `length` hours over the period, and the given workers."""
    names = "\n".join(f'  - name: "{name}"' for name in workers)
    return textwrap.dedent(f"""\
        settings:
          time: ["{start}", "{end}"]
          min_rest: 4
        workers:
        """) + names + textwrap.dedent(f"""
        posts:
          - name: "desk"
            roles: {{any: 1}}
            length: {length}
        """) + history


def write_previous(directory: pathlib.Path, name: str, text: str, extension: str = ".xlsx") -> tuple[int, ...]:
    """Write a previous input and a legal schedule for it, as name.yml and name_schedule<extension>."""
    (directory / f"{name}.yml").write_text(text, encoding="utf-8")
    schedule_input = read_input(directory / f"{name}.yml", read_history=False)
    problem = build_problem(schedule_input)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    write_schedule(build_grid(schedule_input.posts, problem.shifts, problem.workers, assignment),
                   directory / f"{name}_schedule{extension}")
    return assignment


def history_of(*names: str, extension: str = ".xlsx") -> str:
    """A history section listing name.yml and name_schedule<extension> for each name."""
    entries = "".join(f'  - input: "{name}.yml"\n    schedule: "{name}_schedule{extension}"\n' for name in names)
    return "history:\n" + entries


def test_previous_schedules_are_read_relative_to_the_input(tmp_path: pathlib.Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "rosters"
    folder.mkdir()
    first = write_previous(folder, "day1", input_text("2025-01-01T00:00", "2025-01-01T12:00"), ".csv")
    second = write_previous(folder, "day2", input_text("2025-01-01T12:00", "2025-01-02T00:00", length=3), ".ods")
    history = history_of("day1", extension=".csv") + history_of("day2", extension=".ods").removeprefix("history:\n")
    (folder / "day3.yml").write_text(input_text("2025-01-02T00:00", "2025-01-02T12:00", history=history),
                                     encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # paths are relative to the input file, not to where the program runs
    schedule_input = read_input("rosters/day3.yml")
    assert [previous.source for previous in schedule_input.history] == ["day1.yml", "day2.yml"]
    assert [previous.assignment for previous in schedule_input.history] == [first, second]
    assert schedule_input.history[1].schedule_input.posts[0].rules.length.seconds == 3 * 3600  # new hours


def test_a_history_inputs_own_history_is_ignored(tmp_path: pathlib.Path) -> None:
    write_previous(tmp_path, "day1", input_text("2025-01-01T00:00", "2025-01-01T12:00",
                                                history=history_of("missing")))
    (tmp_path / "day2.yml").write_text(input_text("2025-01-01T12:00", "2025-01-02T00:00", history=history_of("day1")),
                                       encoding="utf-8")
    [previous] = read_input(tmp_path / "day2.yml").history
    assert previous.schedule_input.history == ()


@pytest.mark.parametrize(("history", "message"), [
    ('history:\n  - input: "day1.yml"\n', "history entry #1, schedule: is required"),
    ('history:\n  - input: "nowhere.yml"\n    schedule: "day1_schedule.xlsx"\n',
     'history entry #1 \\("nowhere.yml"\\), input: can\'t read'),
    ('history:\n  - input: "day1.yml"\n    schedule: "nowhere.xlsx"\n',
     'history entry #1 \\("day1.yml"\\), schedule: can\'t read'),
    ('history:\n  - input: "day1.yml"\n    schedule: "day1_schedule.xlsx"\n    note: "x"\n', "unknown field 'note'"),
    ("history: 5\n", "history: must be a list"),
])
def test_history_entries_that_cant_be_read(tmp_path: pathlib.Path, history: str, message: str) -> None:
    write_previous(tmp_path, "day1", input_text("2025-01-01T00:00", "2025-01-01T12:00"))
    (tmp_path / "day2.yml").write_text(input_text("2025-01-01T12:00", "2025-01-02T00:00", history=history),
                                       encoding="utf-8")
    with pytest.raises(InputError, match=message):
        read_input(tmp_path / "day2.yml")


def test_a_schedule_that_doesnt_match_its_input(tmp_path: pathlib.Path) -> None:
    write_previous(tmp_path, "day1", input_text("2025-01-01T00:00", "2025-01-01T12:00"), ".csv")
    path = tmp_path / "day1_schedule.csv"
    path.write_text(path.read_text(encoding="utf-8-sig").replace("Anne", "Nobody"), encoding="utf-8-sig")
    (tmp_path / "day2.yml").write_text(input_text("2025-01-01T12:00", "2025-01-02T00:00",
                                                  history=history_of("day1", extension=".csv")), encoding="utf-8")
    with pytest.raises(InputError, match="history entry #1 .*: unknown worker 'Nobody'"):
        read_input(tmp_path / "day2.yml")


@pytest.mark.parametrize(("periods", "message"), [
    ((("2025-01-01T06:00", "2025-01-01T18:00"),), "must end by the time this schedule's starts"),
    ((("2025-01-01T00:00", "2025-01-01T08:00"), ("2025-01-01T04:00", "2025-01-01T10:00")),
     "history entry #2 .*: its period overlaps that of history entry #1"),
])
def test_history_must_be_the_past_and_not_overlap(tmp_path: pathlib.Path, periods: tuple[tuple[str, str], ...],
                                                  message: str) -> None:
    names = [f"before{index}" for index in range(len(periods))]
    for name, (start, end) in zip(names, periods):
        write_previous(tmp_path, name, input_text(start, end))
    (tmp_path / "now.yml").write_text(input_text("2025-01-01T12:00", "2025-01-02T00:00", history=history_of(*names)),
                                      encoding="utf-8")
    with pytest.raises(InputError, match=message):
        read_input(tmp_path / "now.yml")


def test_workers_who_have_left_are_warned_about(tmp_path: pathlib.Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    write_previous(tmp_path, "day1", input_text("2025-01-01T00:00", "2025-01-01T12:00",
                                                workers=("Anne", "Bob", "Cy", "Dana")))
    (tmp_path / "day2.yml").write_text(input_text("2025-01-01T12:00", "2025-01-02T00:00",
                                                  workers=("Anne", "Bob", "Cy", "Eli"), history=history_of("day1")),
                                       encoding="utf-8")
    schedule_input = read_input(tmp_path / "day2.yml")
    assert history_warnings(schedule_input) == [
        'history entry #1 ("day1.yml"): "Dana" is not in this input; their history is ignored']
    assert main([str(tmp_path / "day2.yml"), "-o", str(tmp_path / "out.csv")]) == EXIT_SUCCESS
    assert 'tinyscheg: warning: history entry #1 ("day1.yml"): "Dana" is not in this input' in capsys.readouterr().err


def test_the_command_line_writes_only_the_new_period(tmp_path: pathlib.Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    write_previous(tmp_path, "day1", input_text("2025-01-01T00:00", "2025-01-01T12:00"))
    (tmp_path / "day2.yml").write_text(input_text("2025-01-01T12:00", "2025-01-02T00:00", history=history_of("day1")),
                                       encoding="utf-8")
    output = tmp_path / "day2_schedule.xlsx"
    assert main([str(tmp_path / "day2.yml"), "-o", str(output)]) == EXIT_SUCCESS
    assert capsys.readouterr().out.startswith(f"wrote {output}: 3 shifts, 3 slots, 3 workers")
    schedule_input = read_input(tmp_path / "day2.yml")
    read = read_schedule(output, schedule_input)  # the new period, read with this input alone
    assert hard_constraint_violations(schedule_input, read.slots, read.assignment) == []  # including the boundary


def test_the_audit_judges_a_schedule_together_with_its_history(tmp_path: pathlib.Path,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    write_previous(tmp_path, "day1", input_text("2025-01-01T00:00", "2025-01-01T12:00"))
    (tmp_path / "day2.yml").write_text(input_text("2025-01-01T12:00", "2025-01-02T00:00", history=history_of("day1")),
                                       encoding="utf-8")
    output = tmp_path / "day2_schedule.ods"
    assert main([str(tmp_path / "day2.yml"), "-o", str(output)]) == EXIT_SUCCESS
    capsys.readouterr()
    assert audit_main([str(tmp_path / "day2.yml"), str(output)]) == EXIT_SUCCESS
    report = capsys.readouterr().out
    assert report.startswith("together with its history: 1 previous schedule(s), 3 slots that no fix may change")
    assert "Anne: " in report


def consecutive_text(start: str, end: str, away: str = "", history: str = "") -> str:
    """
    An input for consecutive schedules: 2-hour desk shifts, 2 hours' minimum rest and a rest target of one shift, so
    that no rest falls short and workload alone decides; Cy may be away
    """
    return textwrap.dedent(f"""\
        settings:
          time: ["{start}", "{end}"]
          min_rest: 2
          scoring: {{rest_factor: 1}}
        workers:
          - name: "Anne"
          - name: "Bob"
          - name: "Cy"
            unavailable: [{away}]
        posts:
          - name: "desk"
            roles: {{any: 1}}
            length: 2
        """) + history


def second_day(tmp_path: pathlib.Path) -> list[int]:
    """Write day 2 with day 1 as its history through the command line, and count each worker's new shifts."""
    (tmp_path / "day2.yml").write_text(consecutive_text("2025-01-01T12:00", "2025-01-02T00:00",
                                                        history=history_of("day1", extension=".csv")), encoding="utf-8")
    assert main([str(tmp_path / "day2.yml"), "-o", str(tmp_path / "day2_schedule.xlsx")]) == EXIT_SUCCESS
    assignment = read_schedule(tmp_path / "day2_schedule.xlsx", read_input(tmp_path / "day2.yml")).assignment
    return [assignment.count(worker) for worker in range(3)]


def test_two_consecutive_schedules_the_second_making_up_for_the_first(tmp_path: pathlib.Path) -> None:
    # day 1 is written by the command line, then edited by hand: Anne took all of Cy's shifts
    (tmp_path / "day1.yml").write_text(consecutive_text("2025-01-01T00:00", "2025-01-01T12:00"), encoding="utf-8")
    assert main([str(tmp_path / "day1.yml"), "-o", str(tmp_path / "day1_schedule.csv")]) == EXIT_SUCCESS
    day1 = tmp_path / "day1_schedule.csv"
    day1.write_text(day1.read_text(encoding="utf-8-sig").replace("Cy", "Anne"), encoding="utf-8-sig")
    anne, bob, cy = second_day(tmp_path)
    assert cy > bob > anne  # Cy did nothing before, Anne the most


def test_being_away_in_the_history_is_no_debt(tmp_path: pathlib.Path) -> None:
    (tmp_path / "day1.yml").write_text(consecutive_text("2025-01-01T00:00", "2025-01-01T12:00",
                                                        away='["2025-01-01T00:00", "2025-01-01T12:00"]'),
                                       encoding="utf-8")
    assert main([str(tmp_path / "day1.yml"), "-o", str(tmp_path / "day1_schedule.csv")]) == EXIT_SUCCESS
    counts = second_day(tmp_path)
    assert sum(counts) == 6 and max(counts) - min(counts) <= 1  # Cy was away, so the new shifts are split evenly
