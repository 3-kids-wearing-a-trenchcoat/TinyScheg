"""Tests for tinyscheg.output.grid."""
import datetime as dt
import pathlib

from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.post import Post, ShiftRules, Variation
from tinyscheg.model.shift_generation import generate_shifts
from tinyscheg.model.worker import Worker
from tinyscheg.output.grid import Grid, build_grid
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.timing.daily_window import DailyWindow
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"
GATE = Post("front gate", ShiftRules(dt.timedelta(hours=3), (("any", 1),)), None,
            (Variation(DailyWindow.parse("19:00-07:00"),
                       ShiftRules(dt.timedelta(hours=3), (("security", 1), ("any", 1)))),))
DESK = Post("desk", ShiftRules(dt.timedelta(hours=4), (("any", 1),)), DailyWindow.parse("08:00-20:00"))


def at(day: int, hour: int) -> dt.datetime:
    """A datetime on 2025-01-<day> at hour:00."""
    return dt.datetime(2025, 1, day, hour)


def table(grid: Grid) -> list[list[str]]:
    """The grid as shown: start hour, end hour, then each cell's text."""
    columns = range(len(grid.columns))
    return [[f"{row.start:%d %H}", f"{row.end:%d %H}", *(grid.text(index, column) for column in columns)]
            for index, row in enumerate(grid.rows)]


def test_output_format_example() -> None:
    # the example on the output format page: shifts are gate 06-07 (security, any), gate 07-10, desk 08-12,
    # gate 10-13 and desk 12-13, with slots in that order
    workers = [Worker("Anne"), Worker("Bob"), Worker("Enkidu", roles=frozenset({"security"})), Worker("Jack"),
               Worker("Jill")]
    shifts = generate_shifts([GATE, DESK], DateTimeRange(at(1, 6), at(1, 13)))
    grid = build_grid([GATE, DESK], shifts, workers, [2, 0, 3, 4, 0, 1])
    assert grid.columns == ("front gate", "desk")
    assert table(grid) == [
        ["01 06", "01 07", "Enkidu & Anne", ""],
        ["01 07", "01 08", "Jack", ""],
        ["01 08", "01 10", "Jack", "Jill"],
        ["01 10", "01 12", "Anne", "Jill"],
        ["01 12", "01 13", "Anne", "Bob"],
    ]
    # cells hold the covering shift, so the gate's 07-10 shift is one shift across two rows
    assert grid.cells[1][0] == grid.cells[2][0] == 1
    assert grid.cells[0][1] is None


def test_rows_where_no_post_is_active_are_left_out() -> None:
    shifts = generate_shifts([DESK], DateTimeRange(at(1, 0), at(3, 0)))
    grid = build_grid([DESK], shifts, [Worker("Anne")], [0] * len(shifts))
    assert [(row.start, row.end) for row in grid.rows][2:4] == [(at(1, 16), at(1, 20)), (at(2, 8), at(2, 12))]


def test_a_post_with_no_shifts_gets_an_empty_column() -> None:
    night_desk = Post("night desk", ShiftRules(dt.timedelta(hours=4), (("any", 1),)), DailyWindow.parse("22:00-02:00"))
    shifts = generate_shifts([DESK, night_desk], DateTimeRange(at(1, 8), at(1, 16)))
    grid = build_grid([DESK, night_desk], shifts, [Worker("Anne")], [0, 0])
    assert grid.columns == ("desk", "night desk")
    assert all(row[1] is None for row in grid.cells)


def test_non_latin_names() -> None:
    shifts = generate_shifts([DESK], DateTimeRange(at(1, 8), at(1, 12)))
    grid = build_grid([DESK], shifts, [Worker("ענבל")], [0])
    assert grid.text(0, 0) == "ענבל"


def test_example_schedule_grid_matches_the_assignment() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    problem = build_problem(schedule_input)
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    grid = build_grid(schedule_input.posts, problem.shifts, problem.workers, assignment)
    for shift in problem.shifts:
        column = grid.columns.index(shift.post.name)
        covered = [row for index, row in enumerate(grid.rows) if grid.cells[index][column] == shift.index]
        # the rows a shift covers are consecutive and add up to exactly its time
        assert covered[0].start == shift.time.start and covered[-1].end == shift.time.end
        assert all(earlier.end == later.start for earlier, later in zip(covered, covered[1:]))
        names = grid.shift_names[shift.index].split(" & ")
        assert names == [problem.workers[assignment[slot.index]].name for slot in shift.slots]
    assert all(any(cell is not None for cell in row) for row in grid.cells)


def test_spans_are_each_shifts_block_of_rows() -> None:
    # a shift over two rows, then the next shift with the same workers; the second column opens in the second row
    grid = Grid(("gate", "desk"), (DateTimeRange(at(1, 6), at(1, 7)), DateTimeRange(at(1, 7), at(1, 8)),
                                   DateTimeRange(at(1, 8), at(1, 9))),
                ((0, None), (0, 1), (2, 1)), ("Anne", "Bob", "Anne"))
    assert [(span.column, span.first_row, span.last_row, span.shift_index) for span in grid.spans()] == [
        (0, 0, 1, 0), (0, 2, 2, 2), (1, 1, 2, 1)]
