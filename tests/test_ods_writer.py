"""Tests for tinyscheg.output.ods_writer, reading the written spreadsheet back with odfpy."""
import datetime as dt
import pathlib

from odf import teletype
from odf.config import ConfigItem
from odf.opendocument import load
from odf.table import CoveredTableCell, Table, TableCell, TableRow

from tinyscheg.output.grid import Grid
from tinyscheg.output.ods_writer import write_ods
from tinyscheg.timing.datetime_range import DateTimeRange


def hours(start: int, end: int) -> DateTimeRange:
    """A range on 2025-01-01 from start to end o'clock."""
    return DateTimeRange(dt.datetime(2025, 1, 1, start), dt.datetime(2025, 1, 1, end))


# the gate's first shift covers two rows, then the same workers take its next shift; the desk opens in the second row
GRID = Grid(columns=("ש.ג.", "desk"),
            rows=(hours(6, 7), hours(7, 8), hours(8, 9)),
            cells=((0, None), (0, 1), (2, 1)),
            shift_names=("ענבל & Anne", "Bob", "ענבל & Anne"))


def cells_of(path: pathlib.Path) -> list[list[tuple[str, str, str, str]]]:
    """Each row's cells as (kind, text, value type, rows spanned), kind being "cell" or "covered"."""
    document = load(str(path))
    [table] = document.spreadsheet.getElementsByType(Table)
    rows = []
    for row in table.getElementsByType(TableRow):
        cells = []
        for cell in row.childNodes:
            if cell.qname == CoveredTableCell().qname:
                cells.append(("covered", "", "", ""))
            elif cell.qname == TableCell().qname:
                cells.append(("cell", teletype.extractText(cell), cell.getAttribute("valuetype") or "",
                              cell.getAttribute("numberrowsspanned") or ""))
        rows.append(cells)
    return rows


def test_the_grid_with_merged_shifts(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "schedule.ods"
    write_ods(GRID, path)
    header, *rows = cells_of(path)
    assert [text for _, text, _, _ in header] == ["start", "end", "ש.ג.", "desk"]
    assert [cell[2:] for cell in rows[0][2:]] == [("string", "2"), ("", "")]   # gate merged over two rows; desk shut
    assert [cell[0] for cell in rows[1][2:]] == ["covered", "cell"]
    assert rows[1][3][1:] == ("Bob", "string", "2")
    assert rows[2][2][1:] == ("ענבל & Anne", "string", "")                     # the same workers' next shift
    assert rows[2][3][0] == "covered"


def test_times_are_date_time_cells(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "schedule.ods"
    write_ods(GRID, path)
    document = load(str(path))
    first_row = document.spreadsheet.getElementsByType(TableRow)[1]
    start, end = first_row.getElementsByType(TableCell)[:2]
    assert (start.getAttribute("valuetype"), start.getAttribute("datevalue")) == ("date", "2025-01-01T06:00:00")
    assert end.getAttribute("datevalue") == "2025-01-01T07:00:00"
    assert teletype.extractText(start) == "2025-01-01 06:00"


def test_header_and_time_columns_are_frozen(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "schedule.ods"
    write_ods(GRID, path)
    items = {item.getAttribute("name"): teletype.extractText(item)
             for item in load(str(path)).settings.getElementsByType(ConfigItem)}
    assert items["HorizontalSplitPosition"] == "2" and items["VerticalSplitPosition"] == "1"
    assert items["HorizontalSplitMode"] == items["VerticalSplitMode"] == "2"
