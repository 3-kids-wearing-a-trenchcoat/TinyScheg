"""Tests for tinyscheg.output.xlsx_writer, reading the written workbook back with openpyxl."""
import datetime as dt
import pathlib

from openpyxl import load_workbook

from tinyscheg.output.grid import Grid
from tinyscheg.output.xlsx_writer import DATETIME_FORMAT, write_xlsx
from tinyscheg.timing.datetime_range import DateTimeRange


def hours(start: int, end: int) -> DateTimeRange:
    """A range on 2025-01-01 from start to end o'clock."""
    return DateTimeRange(dt.datetime(2025, 1, 1, start), dt.datetime(2025, 1, 1, end))


# the gate's first shift covers two rows, then the same workers take its next shift; the desk opens in the second row
GRID = Grid(columns=("ש.ג.", "desk"),
            rows=(hours(6, 7), hours(7, 8), hours(8, 9)),
            cells=((0, None), (0, 1), (2, 1)),
            shift_names=("ענבל & Anne", "Bob", "ענבל & Anne"))


def written(tmp_path: pathlib.Path, grid: Grid = GRID):  # type: ignore[no-untyped-def]
    """The grid written as XLSX and read back: its only sheet."""
    path = tmp_path / "schedule.xlsx"
    write_xlsx(grid, path)
    workbook = load_workbook(path)
    assert len(workbook.worksheets) == 1
    return workbook.active


def test_header_and_times(tmp_path: pathlib.Path) -> None:
    sheet = written(tmp_path)
    assert [cell.value for cell in sheet[1]] == ["start", "end", "ש.ג.", "desk"]
    assert all(cell.font.bold for cell in sheet[1])
    for row_index, row in enumerate(GRID.rows, start=2):
        start, end = sheet.cell(row_index, 1), sheet.cell(row_index, 2)
        assert (start.value, end.value) == (row.start, row.end)  # real date-time values, not text
        assert start.number_format == end.number_format == DATETIME_FORMAT


def test_a_shift_covering_several_rows_is_one_merged_cell(tmp_path: pathlib.Path) -> None:
    sheet = written(tmp_path)
    assert sorted(str(cells) for cells in sheet.merged_cells.ranges) == ["C2:C3", "D3:D4"]
    assert sheet["C2"].value == "ענבל & Anne" and sheet["D3"].value == "Bob"
    assert sheet["C4"].value == "ענבל & Anne"  # the same workers' next shift is a cell of its own
    assert sheet["D2"].value is None           # the desk isn't active yet


def test_headers_and_time_columns_are_frozen(tmp_path: pathlib.Path) -> None:
    assert written(tmp_path).freeze_panes == "C2"


def test_post_columns_fit_their_longest_text(tmp_path: pathlib.Path) -> None:
    long_name = "Gilgamesh & Enkidu & Shamhat"
    grid = Grid(("desk",), (hours(8, 12),), ((0,),), (long_name,))
    assert written(tmp_path, grid).column_dimensions["C"].width > len(long_name)
