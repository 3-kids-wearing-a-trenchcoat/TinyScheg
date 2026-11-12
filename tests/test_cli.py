"""Tests for tinyscheg.cli, including the end-to-end test."""
import pathlib
import textwrap

import pytest
from openpyxl import load_workbook

from schedule_checker import hard_constraint_violations
from schedule_reader import read_schedule
from tinyscheg.cli import EXIT_NO_SCHEDULE, EXIT_SUCCESS, EXIT_USAGE, default_output_path, describe_penalty, main
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_best_schedule
from tinyscheg.output.writers import WRITERS, UnsupportedFormatError, writer_for
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.constants import build_constants
from tinyscheg.scoring.penalty import Penalty, score

# small enough for branch and bound to finish at once: 8 slots, 5 workers
SMALL = """
settings:
  time: ["2025-01-01T00:00", "2025-01-01T12:00"]
  min_rest: 2
workers:
  - name: "Anne"
    likes: ["Bob"]
  - name: "Bob"
  - name: "Cy"
    roles: ["supervisor"]
    dislikes: ["Anne"]
  - name: "Dan"
    roles: ["supervisor"]
  - name: "Eve"
posts:
  - name: "front gate"
    roles: {any: 2}
    length: 4
  - name: "desk"
    roles: {supervisor: 1}
    length: 6
"""

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


# --- end to end ---

def test_end_to_end(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write(tmp_path, SMALL)
    output = tmp_path / "schedule.csv"
    assert main([str(input_path), "-o", str(output)]) == EXIT_SUCCESS
    captured = capsys.readouterr()
    wrote, penalty = captured.out.splitlines()
    assert wrote == f"wrote {output}: 5 shifts, 8 slots, 5 workers"
    schedule_input = read_input(input_path)
    problem = build_problem(schedule_input)
    assignment = read_schedule(output, schedule_input).assignment
    assert hard_constraint_violations(schedule_input, problem.slots, assignment) == []
    # the schedule written is the best one, and the penalty shown is its own
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    best = find_best_schedule(problem, constants)
    assert assignment == best.assignment
    assert penalty == f"{describe_penalty(score(constants, assignment))}, the best possible"
    # each better schedule found is reported on standard error, the last being the one written
    progress = captured.err.splitlines()
    assert progress and all(line.startswith("tinyscheg: found penalty ") for line in progress)
    assert progress[-1].startswith(f"tinyscheg: found penalty {score(constants, assignment).total:.2f} after ")



def test_end_to_end_xlsx(tmp_path: pathlib.Path) -> None:
    input_path = write(tmp_path, SMALL)
    output = tmp_path / "schedule.xlsx"
    assert main([str(input_path), "-o", str(output)]) == EXIT_SUCCESS
    sheet = load_workbook(output).active
    assert [cell.value for cell in sheet[1]][:2] == ["start", "end"]
    assert sheet.max_row > 1


def test_describe_penalty() -> None:
    assert describe_penalty(Penalty(2.8449, 0.3125, 4.6188, 0.1201)) == (
        "penalty 2.84 (likes 0.31, workload 4.62, rest 0.12)")


def test_default_output_is_next_to_the_input(tmp_path: pathlib.Path) -> None:
    input_path = write(tmp_path, SMALL, "week1.yml")
    assert default_output_path(input_path) == tmp_path / "week1_schedule.csv"
    assert main([str(input_path)]) == EXIT_SUCCESS
    assert (tmp_path / "week1_schedule.csv").exists()


def test_existing_output_is_overwritten(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "schedule.csv"
    output.write_text("old", encoding="utf-8")
    assert main([str(write(tmp_path, SMALL)), "-o", str(output)]) == EXIT_SUCCESS
    assert output.read_text(encoding="utf-8-sig").startswith("start,end,front gate,desk")


# --- failures write nothing ---

def test_unsupported_format_is_checked_first(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "schedule.txt"
    assert main([str(tmp_path / "missing.yml"), "-o", str(output)]) == EXIT_USAGE
    assert f'unsupported output format ".txt" (supported: {", ".join(WRITERS)})' in capsys.readouterr().err
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
