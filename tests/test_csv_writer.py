"""Tests for tinyscheg.output.csv_writer."""
import csv
import datetime as dt
import pathlib

from tinyscheg.output.csv_writer import write_csv
from tinyscheg.output.grid import Grid
from tinyscheg.timing.datetime_range import DateTimeRange


def hours(start: int, end: int) -> DateTimeRange:
    """A range on 2025-01-01 from start to end o'clock."""
    return DateTimeRange(dt.datetime(2025, 1, 1, start), dt.datetime(2025, 1, 1, end))


# the gate's first shift covers two rows; the desk opens in the second row
GRID = Grid(columns=("ש.ג.", "desk"),
            rows=(hours(6, 7), hours(7, 8)),
            cells=((0, None), (0, 1)),
            shift_names=("ענבל & Anne", "Bob"))


def test_csv_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "schedule.csv"
    write_csv(GRID, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # byte order mark
    assert raw.decode("utf-8-sig").splitlines() == [
        "start,end,ש.ג.,desk",
        "2025-01-01T06:00:00,2025-01-01T07:00:00,ענבל & Anne,",
        "2025-01-01T07:00:00,2025-01-01T08:00:00,ענבל & Anne,Bob",
    ]


def test_csv_reads_back_as_the_grid_text(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "schedule.csv"
    write_csv(GRID, path)
    with open(path, encoding="utf-8-sig", newline="") as file:
        header, *rows = list(csv.reader(file))
    assert header == ["start", "end", "ש.ג.", "desk"]
    for index, row in enumerate(rows):
        assert row[0] == GRID.rows[index].start.isoformat()
        assert row[2:] == [GRID.text(index, column) for column in range(2)]


def test_names_with_commas_are_quoted(tmp_path: pathlib.Path) -> None:
    grid = Grid(("desk",), (hours(8, 12),), ((0,),), ("Smith, Anne",))
    path = tmp_path / "schedule.csv"
    write_csv(grid, path)
    with open(path, encoding="utf-8-sig", newline="") as file:
        assert list(csv.reader(file))[1][2] == "Smith, Anne"
