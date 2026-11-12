"""Tests for tinyscheg.parsing.schedule_reader, on schedules written in every format."""
import datetime as dt
import pathlib

import pytest
from openpyxl import load_workbook

from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.output.csv_writer import CSV_ENCODING
from tinyscheg.output.grid import build_grid
from tinyscheg.output.writers import write_schedule
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.schedule_reader import ScheduleReadError, read_schedule
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"
FORMATS = (".csv", ".xlsx", ".ods")


def write_example(tmp_path: pathlib.Path, extension: str) -> tuple[pathlib.Path, tuple[int, ...]]:
    """The example's schedule, written in a format, and the assignment it was written from."""
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    path = tmp_path / f"schedule{extension}"
    write_schedule(build_grid(schedule_input.posts, problem.shifts, problem.workers, assignment), path)
    return path, assignment


@pytest.mark.parametrize("extension", FORMATS)
def test_reading_back_gives_the_written_schedule(tmp_path: pathlib.Path, extension: str) -> None:
    path, assignment = write_example(tmp_path, extension)
    schedule_input = read_input(EXAMPLE_INPUT)
    read = read_schedule(path, schedule_input)
    problem = build_problem(schedule_input)
    assert read.assignment == assignment
    assert read.shifts == problem.shifts and read.slots == problem.slots


@pytest.mark.parametrize("extension", FORMATS)
def test_consecutive_shifts_of_the_same_workers_are_read_apart(tmp_path: pathlib.Path, extension: str) -> None:
    # with no minimum rest, Anne takes two back-to-back shifts: identical rows in CSV, separate merged cells elsewhere
    period = DateTimeRange(dt.datetime(2025, 1, 1, 8), dt.datetime(2025, 1, 1, 16))
    post = Post("desk", ShiftRules(dt.timedelta(hours=2), (("any", 1),)))
    schedule_input = ScheduleInput(Settings(period, dt.timedelta(0)), (Worker("Anne"), Worker("Bob")), (post,))
    problem = build_problem(schedule_input)
    assignment = (0, 0, 1, 0)
    path = tmp_path / f"schedule{extension}"
    write_schedule(build_grid(schedule_input.posts, problem.shifts, problem.workers, assignment), path)
    assert read_schedule(path, schedule_input).assignment == assignment


def test_a_hand_edited_spreadsheet_is_read_as_edited(tmp_path: pathlib.Path) -> None:
    path, assignment = write_example(tmp_path, ".xlsx")
    schedule_input = read_input(EXAMPLE_INPUT)
    workbook = load_workbook(path)
    sheet = workbook.active
    first = next(cell for cell in sheet["C"][1:] if cell.value and " & " not in cell.value)  # a one-worker shift
    names = [worker.name for worker in schedule_input.workers]
    replacement = next(name for name in names if name != first.value)
    first.value = replacement
    workbook.save(path)
    read = read_schedule(path, schedule_input)
    assert sum(a != b for a, b in zip(read.assignment, assignment)) == 1
    assert names.index(replacement) in read.assignment


@pytest.mark.parametrize(("old", "new", "message"), [
    ("Jack", "Nobody", "unknown worker 'Nobody'"),
    ("front gate", "back gate", "no column for post 'front gate'"),
])
def test_a_file_that_doesnt_match_the_input(tmp_path: pathlib.Path, old: str, new: str, message: str) -> None:
    path, _ = write_example(tmp_path, ".csv")
    path.write_text(path.read_text(encoding=CSV_ENCODING).replace(old, new), encoding=CSV_ENCODING)
    with pytest.raises(ScheduleReadError, match=message):
        read_schedule(path, read_input(EXAMPLE_INPUT))


def test_a_missing_row(tmp_path: pathlib.Path) -> None:
    path, _ = write_example(tmp_path, ".csv")
    lines = path.read_text(encoding=CSV_ENCODING).splitlines(keepends=True)
    path.write_text("".join(lines[:-1]), encoding=CSV_ENCODING)
    with pytest.raises(ScheduleReadError, match="no row starting at"):
        read_schedule(path, read_input(EXAMPLE_INPUT))


def test_a_start_that_isnt_a_time(tmp_path: pathlib.Path) -> None:
    path, _ = write_example(tmp_path, ".csv")
    lines = path.read_text(encoding=CSV_ENCODING).splitlines(keepends=True)
    lines[1] = "soon" + lines[1][lines[1].index(","):]
    path.write_text("".join(lines), encoding=CSV_ENCODING)
    with pytest.raises(ScheduleReadError, match="row 2: the start 'soon' isn't a date and time"):
        read_schedule(path, read_input(EXAMPLE_INPUT))


def test_an_unsupported_format(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ScheduleReadError, match='unsupported schedule format ".txt"'):
        read_schedule(tmp_path / "schedule.txt", read_input(EXAMPLE_INPUT))
