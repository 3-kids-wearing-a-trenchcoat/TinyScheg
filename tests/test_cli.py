"""Tests for tinyscheg.cli, including the end-to-end test."""
import csv
import pathlib
import shutil
import textwrap

import pytest

from schedule_checker import hard_constraint_violations
from tinyscheg.cli import EXIT_NO_SCHEDULE, EXIT_SUCCESS, EXIT_USAGE, default_output_path, describe_penalty, main
from tinyscheg.csp.problem import build_problem
from tinyscheg.output.writers import UnsupportedFormatError, writer_for
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.constants import build_constants
from tinyscheg.scoring.penalty import Penalty, score

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"

# three workers for two back-to-back shifts of two, with an hour's rest: every slot needs a different worker
STUCK = """
settings:
  time: ["2025-01-01T00:00", "2025-01-01T08:00"]
  min_rest: 1
workers:
  - name: "Anne"
  - name: "Bob"
  - name: "Cy"
posts:
  - name: "gate"
    roles: {any: 2}
    length: 4
"""

UNFILLABLE = """
settings:
  time: ["2025-01-01T00:00", "2025-01-01T04:00"]
workers:
  - name: "Anne"
posts:
  - name: "desk"
    roles: {supervisor: 1}
    length: 4
"""


def write(tmp_path: pathlib.Path, text: str, name: str = "input.yml") -> pathlib.Path:
    """Write an input file and return its path."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def read_assignment(csv_path: pathlib.Path, input_path: pathlib.Path) -> tuple:
    """
    Read a written schedule back into a worker index per slot: each shift's names, from the row where it starts in
    its post's column, in slot order
    """
    schedule_input = read_input(input_path)
    problem = build_problem(schedule_input)
    with open(csv_path, encoding="utf-8-sig", newline="") as file:
        header, *rows = list(csv.reader(file))
    row_by_start = {row[0]: row for row in rows}
    worker_index = {worker.name: index for index, worker in enumerate(schedule_input.workers)}
    assignment: list[int | None] = [None] * len(problem.slots)
    for shift in problem.shifts:
        cell = row_by_start[shift.time.start.isoformat()][header.index(shift.post.name)]
        for slot, name in zip(shift.slots, cell.split(" & "), strict=True):
            assignment[slot.index] = worker_index[name]
    return tuple(assignment)


# --- end to end ---

def test_example_end_to_end(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "schedule.csv"
    assert main([str(EXAMPLE_INPUT), "-o", str(output)]) == EXIT_SUCCESS
    wrote, penalty = capsys.readouterr().out.splitlines()
    assert wrote.startswith(f"wrote {output}: ")
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assignment = read_assignment(output, EXAMPLE_INPUT)
    assert hard_constraint_violations(schedule_input, problem.slots, assignment) == []
    # the penalty shown is the written schedule's
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    assert penalty == describe_penalty(score(constants, assignment))


def test_describe_penalty() -> None:
    assert describe_penalty(Penalty(2.8449, 0.3125, 4.6188, 0.1201)) == (
        "penalty 2.84 (likes 0.31, workload 4.62, rest 0.12)")


def test_default_output_is_next_to_the_input(tmp_path: pathlib.Path) -> None:
    input_path = tmp_path / "week1.yml"
    shutil.copy(EXAMPLE_INPUT, input_path)
    assert default_output_path(input_path) == tmp_path / "week1_schedule.csv"
    assert main([str(input_path)]) == EXIT_SUCCESS
    assert (tmp_path / "week1_schedule.csv").exists()


def test_existing_output_is_overwritten(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "schedule.csv"
    output.write_text("old", encoding="utf-8")
    assert main([str(EXAMPLE_INPUT), "-o", str(output)]) == EXIT_SUCCESS
    assert output.read_text(encoding="utf-8-sig").startswith("start,end,front gate,desk")


# --- failures write nothing ---

def test_unsupported_format_is_checked_first(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "schedule.txt"
    assert main([str(tmp_path / "missing.yml"), "-o", str(output)]) == EXIT_USAGE
    assert 'unsupported output format ".txt" (supported: .csv)' in capsys.readouterr().err
    assert not output.exists()


def test_missing_input(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "missing.yml")]) == EXIT_USAGE
    assert "can't read" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_invalid_input(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write(tmp_path, UNFILLABLE.replace("length: 4", "length: 0"))
    assert main([str(input_path)]) == EXIT_USAGE
    error = capsys.readouterr().err
    assert error.startswith("tinyscheg: invalid input:") and "length: must be more than 0 hours" in error
    assert not default_output_path(input_path).exists()


def test_unfillable_slots_are_listed(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write(tmp_path, UNFILLABLE)
    assert main([str(input_path)]) == EXIT_NO_SCHEDULE
    assert capsys.readouterr().err == ("tinyscheg: no legal schedule exists:\n"
                                       '  - no worker can fill desk, 2025-01-01 00:00–04:00 (role "supervisor")\n')
    assert not default_output_path(input_path).exists()


def test_search_failure_says_where_it_got_stuck(tmp_path: pathlib.Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write(tmp_path, STUCK)
    output = tmp_path / "schedule.csv"
    output.write_text("an earlier schedule", encoding="utf-8")
    assert main([str(input_path), "-o", str(output)]) == EXIT_NO_SCHEDULE
    assert capsys.readouterr().err == ("tinyscheg: no legal schedule exists; the search filled at most 2 of 4 slots, "
                                       'and got stuck at gate, 2025-01-01 04:00–08:00 (role "any")\n')
    assert output.read_text(encoding="utf-8") == "an earlier schedule"  # left untouched


# --- writers ---

@pytest.mark.parametrize("name", ["schedule.CSV", "schedule.csv"])
def test_writer_for_ignores_case(name: str) -> None:
    assert writer_for(name) is writer_for("x.csv")


def test_writer_for_no_extension() -> None:
    with pytest.raises(UnsupportedFormatError, match="no extension"):
        writer_for("schedule")
