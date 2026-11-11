"""Tests for tools/schedule_reader.py."""
import pathlib

import pytest

from schedule_reader import ScheduleReadError, read_schedule
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.output.csv_writer import CSV_ENCODING, write_csv
from tinyscheg.output.grid import build_grid
from tinyscheg.parsing.input_reader import read_input

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"


@pytest.fixture
def written(tmp_path: pathlib.Path) -> tuple[pathlib.Path, tuple[int, ...]]:
    """The example's schedule, written as CSV, and the assignment it was written from."""
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    path = tmp_path / "schedule.csv"
    write_csv(build_grid(schedule_input.posts, problem.shifts, problem.workers, assignment), path)
    return path, assignment


def test_reading_back_gives_the_written_schedule(written: tuple[pathlib.Path, tuple[int, ...]]) -> None:
    path, assignment = written
    schedule_input = read_input(EXAMPLE_INPUT)
    read = read_schedule(path, schedule_input)
    problem = build_problem(schedule_input)
    assert read.assignment == assignment
    assert read.shifts == problem.shifts and read.slots == problem.slots


@pytest.mark.parametrize(("old", "new", "message"), [
    ("Jack", "Nobody", "unknown worker 'Nobody'"),
    ("front gate", "back gate", "no column for post 'front gate'"),
])
def test_a_file_that_doesnt_match_the_input(written: tuple[pathlib.Path, tuple[int, ...]], old: str, new: str,
                                            message: str) -> None:
    path, _ = written
    path.write_text(path.read_text(encoding=CSV_ENCODING).replace(old, new), encoding=CSV_ENCODING)
    with pytest.raises(ScheduleReadError, match=message):
        read_schedule(path, read_input(EXAMPLE_INPUT))


def test_a_missing_row(written: tuple[pathlib.Path, tuple[int, ...]]) -> None:
    path, _ = written
    lines = path.read_text(encoding=CSV_ENCODING).splitlines(keepends=True)
    path.write_text("".join(lines[:-1]), encoding=CSV_ENCODING)
    with pytest.raises(ScheduleReadError, match="no row starting at"):
        read_schedule(path, read_input(EXAMPLE_INPUT))
