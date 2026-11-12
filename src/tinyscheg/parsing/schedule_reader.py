"""
Reading a written schedule file (CSV, XLSX or ODS) back, given the input it was made for (ADR 0029): each shift
generated from the input is read from the cell where it starts, in its post's column. Independent of
tinyscheg.output: the file's layout (ADR 0019) is all it relies on.
"""
from __future__ import annotations

import csv
import datetime as dt
import pathlib
from collections.abc import Callable
from dataclasses import dataclass

from odf import teletype
from odf.element import Element
from odf.opendocument import load as load_ods
from odf.table import CoveredTableCell, Table, TableCell, TableRow
from openpyxl import load_workbook

from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.model.shift_generation import all_slots, generate_shifts
from tinyscheg.model.worker import NAME_SEPARATOR

CSV_READ_ENCODING = "utf-8-sig"  # reads UTF-8 with or without a byte order mark
START_COLUMN = 0                 # the column holding each row's start time; the post columns are found by header
HEADER_ROW = 0
ODS_REPEAT_LIMIT = 1000          # a repeated ODS row or cell (as spreadsheets write trailing empty space) is expanded
                                 # only up to this many times; anything beyond is empty padding
_CELL = TableCell().qname         # the ODS element names of a cell and of a cell covered by a merged one
_COVERED = CoveredTableCell().qname


@dataclass(frozen=True, slots=True)
class ReadSchedule:
    """A schedule read back: its shifts and slots in stable order, and a worker index per slot."""
    shifts: tuple[Shift, ...]
    slots: tuple[Slot, ...]
    assignment: tuple[int, ...]


class ScheduleReadError(ValueError):
    """
    The file can't be read as a schedule for the input: an unsupported format, a missing post column or shift row, a
    wrong number of names, or an unknown name.
    """


@dataclass(frozen=True, slots=True)
class _Table:
    """A schedule file's content: the header's texts, and each row's cell texts by its start time."""
    header: list[str]
    rows: dict[dt.datetime, list[str]]


def read_schedule(path: str | pathlib.Path, schedule_input: ScheduleInput) -> ReadSchedule:
    """
    Read a written schedule back
    :param path: the schedule file; its extension (.csv, .xlsx or .ods, in any case) gives the format
    :param schedule_input: ScheduleInput the schedule was made for, whose shifts are read
    :return: the ReadSchedule
    :raises ScheduleReadError: if the format isn't supported or the file doesn't match the input
    :raises OSError: if the file can't be read
    """
    path = pathlib.Path(path)
    extension = path.suffix.lower()
    if extension not in _READERS:
        raise ScheduleReadError(f'unsupported schedule format "{extension}" (supported: {", ".join(_READERS)})')
    table = _READERS[extension](path)
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    slots = all_slots(shifts)
    worker_index = {worker.name: index for index, worker in enumerate(schedule_input.workers)}
    assignment = [-1] * len(slots)
    for shift in shifts:
        where = f"{shift.post.name} at {shift.time.start.isoformat()}"
        cell = _cell(table, shift)
        names = cell.split(NAME_SEPARATOR) if cell else []
        if len(names) != len(shift.slots):
            raise ScheduleReadError(f"{where}: expected {len(shift.slots)} names, got {cell!r}")
        for slot, name in zip(shift.slots, names):
            if name not in worker_index:
                raise ScheduleReadError(f"{where}: unknown worker {name!r}")
            assignment[slot.index] = worker_index[name]
    return ReadSchedule(shifts, slots, tuple(assignment))


def _cell(table: _Table, shift: Shift) -> str:
    """The text of the cell where a shift starts, in its post's column."""
    if shift.post.name not in table.header:
        raise ScheduleReadError(f"no column for post {shift.post.name!r}")
    if shift.time.start not in table.rows:
        raise ScheduleReadError(f"no row starting at {shift.time.start.isoformat()}")
    row = table.rows[shift.time.start]
    column = table.header.index(shift.post.name)
    return row[column] if column < len(row) else ""


def _table(rows: list[list[object]]) -> _Table:
    """
    A table from a file's rows of cell values, each a str, a datetime or None
    :raises ScheduleReadError: if a row's start isn't a time
    """
    if not rows:
        raise ScheduleReadError("the file is empty")
    header = ["" if value is None else str(value).strip() for value in rows[HEADER_ROW]]
    by_start: dict[dt.datetime, list[str]] = {}
    for number, row in enumerate(rows[HEADER_ROW + 1:], start=HEADER_ROW + 2):
        if all(value is None or str(value).strip() == "" for value in row):
            continue  # an empty row, as spreadsheets may leave at the end
        start = _moment(row[START_COLUMN] if row else None, number)
        by_start[start] = ["" if value is None else str(value).strip() for value in row]
    return _Table(header, by_start)


def _moment(value: object, row_number: int) -> dt.datetime:
    """A start time, from a date-time cell or ISO 8601 text."""
    if isinstance(value, dt.datetime):
        return value
    try:
        return dt.datetime.fromisoformat(str(value).strip())
    except ValueError:
        raise ScheduleReadError(f"row {row_number}: the start {value!r} isn't a date and time") from None


def _read_csv(path: pathlib.Path) -> _Table:
    """A CSV schedule's table; times are ISO 8601 text."""
    with open(path, encoding=CSV_READ_ENCODING, newline="") as file:
        return _table([list(row) for row in csv.reader(file)])


def _read_xlsx(path: pathlib.Path) -> _Table:
    """An XLSX schedule's table, from its first sheet; a merged cell's value is in its first cell, as a span's is."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return _table([list(row) for row in workbook.worksheets[0].iter_rows(values_only=True)])
    finally:
        workbook.close()


def _read_ods(path: pathlib.Path) -> _Table:
    """An ODS schedule's table, from its first sheet; covered (merged) cells read as empty."""
    tables = load_ods(str(path)).spreadsheet.getElementsByType(Table)
    if not tables:
        raise ScheduleReadError("the file has no sheet")
    rows: list[list[object]] = []
    for row in tables[0].getElementsByType(TableRow):
        values: list[object] = []
        for cell in row.childNodes:
            if cell.qname not in (_CELL, _COVERED):
                continue
            value = _ods_value(cell) if cell.qname == _CELL else None
            values.extend([value] * _repeated(cell, "numbercolumnsrepeated"))
        repeats = _repeated(row, "numberrowsrepeated")
        if any(value is not None for value in values):
            rows.extend(list(values) for _ in range(repeats))
        else:
            rows.append(values)
    return _table(rows)


def _ods_value(cell: Element) -> object:
    """An ODS cell's value: a datetime for a date cell, its text otherwise, None if empty."""
    if cell.getAttribute("valuetype") == "date":
        return dt.datetime.fromisoformat(cell.getAttribute("datevalue"))
    text = teletype.extractText(cell)
    return text or None


def _repeated(element: Element, attribute: str) -> int:
    """How many times an ODS row or cell repeats, up to ODS_REPEAT_LIMIT."""
    value = element.getAttribute(attribute)
    return min(int(value), ODS_REPEAT_LIMIT) if value else 1


_READERS: dict[str, Callable[[pathlib.Path], _Table]] = {".csv": _read_csv, ".xlsx": _read_xlsx, ".ods": _read_ods}
