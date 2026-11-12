"""Writing the grid as an OpenDocument spreadsheet (ADR 0019), with odfpy."""
from __future__ import annotations

import datetime as dt
import pathlib

from odf.config import ConfigItem, ConfigItemMapEntry, ConfigItemMapIndexed, ConfigItemMapNamed, ConfigItemSet
from odf.number import DateStyle, Day, Hours, Minutes, Month, Text, Year
from odf.opendocument import OpenDocumentSpreadsheet
from odf.style import Style, TableCellProperties, TableColumnProperties, TextProperties
from odf.table import CoveredTableCell, Table, TableCell, TableColumn, TableRow
from odf.text import P

from tinyscheg.output.grid import Grid
from tinyscheg.output.xlsx_writer import (COLUMN_PADDING, MIN_POST_COLUMN_WIDTH, SHEET_TITLE, TIME_COLUMN_WIDTH,
                                          TIME_HEADERS)

SHOWN_DATETIME = "%Y-%m-%d %H:%M"   # the text shown in time cells, matching their date style (yyyy-mm-dd hh:mm)
CHARACTER_WIDTH_CM = 0.23           # the width of one character, for column widths given in characters
FROZEN_ROWS = 1                     # the header row
FROZEN_COLUMNS = len(TIME_HEADERS)  # the time columns
SPLIT_MODE_FROZEN = 2               # the OpenDocument view setting for a frozen (rather than split) pane


def write_ods(grid: Grid, path: str | pathlib.Path) -> None:
    """
    Write a grid as an OpenDocument spreadsheet, laid out as write_xlsx lays out a workbook
    :param grid: Grid
    :param path: the file to write; it's replaced if it exists
    :return: None. One sheet: a bold header row of start, end, then the post names, frozen with the time columns;
    times as date-time cells; a shift covering several rows as one merged cell; an inactive post's cells empty
    """
    document = OpenDocumentSpreadsheet()
    styles = _Styles(document)
    table = Table(name=SHEET_TITLE)
    widths = [TIME_COLUMN_WIDTH] * len(TIME_HEADERS) + _post_widths(grid)
    for index, width in enumerate(widths):
        table.addElement(TableColumn(stylename=styles.column(document, index, width)))
    header = TableRow()
    for text in (*TIME_HEADERS, *grid.columns):
        header.addElement(_text_cell(text, styles.header))
    table.addElement(header)
    # what each cell holds: a span's first cell its names, the cells below it covered, any other cell empty
    spans = {(span.first_row, span.column): span for span in grid.spans()}
    covered = {(row, span.column) for span in spans.values() for row in range(span.first_row + 1, span.last_row + 1)}
    for row_index, row in enumerate(grid.rows):
        table_row = TableRow()
        for moment in (row.start, row.end):
            table_row.addElement(_datetime_cell(moment, styles.datetime))
        for column in range(len(grid.columns)):
            span = spans.get((row_index, column))
            if span is not None:
                cell = _text_cell(grid.shift_names[span.shift_index], styles.names)
                if span.last_row > span.first_row:
                    cell.setAttribute("numberrowsspanned", str(span.last_row - span.first_row + 1))
                table_row.addElement(cell)
            elif (row_index, column) in covered:
                table_row.addElement(CoveredTableCell())
            else:
                table_row.addElement(TableCell())
        table.addElement(table_row)
    document.spreadsheet.addElement(table)
    document.settings.addElement(_frozen_panes())
    document.save(str(path))


class _Styles:
    """The document's cell styles, added to it once."""

    def __init__(self, document: OpenDocumentSpreadsheet) -> None:
        """
        Add the cell styles to a document
        :param document: OpenDocumentSpreadsheet
        """
        date_style = DateStyle(name="datetime")
        for part in (Year(style="long"), Text(text="-"), Month(style="long"), Text(text="-"), Day(style="long"),
                     Text(text=" "), Hours(style="long"), Text(text=":"), Minutes(style="long")):
            date_style.addElement(part)
        document.automaticstyles.addElement(date_style)
        self.header = Style(name="header", family="table-cell")
        self.header.addElement(TextProperties(fontweight="bold"))
        self.datetime = Style(name="datetimecell", family="table-cell", datastylename="datetime")
        self.names = Style(name="names", family="table-cell")
        self.names.addElement(TableCellProperties(verticalalign="middle"))
        for style in (self.header, self.datetime, self.names):
            document.automaticstyles.addElement(style)

    @staticmethod
    def column(document: OpenDocumentSpreadsheet, index: int, width: float) -> Style:
        """Add the style of a column of the given width, in characters, and return it."""
        style = Style(name=f"column{index}", family="table-column")
        style.addElement(TableColumnProperties(columnwidth=f"{width * CHARACTER_WIDTH_CM:.2f}cm"))
        document.automaticstyles.addElement(style)
        return style


def _post_widths(grid: Grid) -> list[float]:
    """Each post column's width in characters: its longest text plus padding, at least the minimum."""
    texts: list[list[str]] = [[name] for name in grid.columns]
    for span in grid.spans():
        texts[span.column].append(grid.shift_names[span.shift_index])
    return [max(MIN_POST_COLUMN_WIDTH, max(len(text) for text in column) + COLUMN_PADDING) for column in texts]


def _text_cell(text: str, style: Style) -> TableCell:
    """A cell holding text."""
    cell = TableCell(valuetype="string", stylename=style)
    cell.addElement(P(text=text))
    return cell


def _datetime_cell(moment: dt.datetime, style: Style) -> TableCell:
    """A cell holding a date-time value, with its text as shown."""
    cell = TableCell(valuetype="date", datevalue=moment.isoformat(), stylename=style)
    cell.addElement(P(text=moment.strftime(SHOWN_DATETIME)))
    return cell


def _frozen_panes() -> ConfigItemSet:
    """The view settings that freeze the header row and the time columns of the sheet."""
    sheet = ConfigItemMapEntry(name=SHEET_TITLE)
    for name, kind, value in (("HorizontalSplitMode", "short", SPLIT_MODE_FROZEN),
                              ("VerticalSplitMode", "short", SPLIT_MODE_FROZEN),
                              ("HorizontalSplitPosition", "int", FROZEN_COLUMNS),
                              ("VerticalSplitPosition", "int", FROZEN_ROWS),
                              ("PositionRight", "int", FROZEN_COLUMNS),
                              ("PositionBottom", "int", FROZEN_ROWS)):
        item = ConfigItem(name=name, type=kind)
        item.addText(str(value))
        sheet.addElement(item)
    tables = ConfigItemMapNamed(name="Tables")
    tables.addElement(sheet)
    view = ConfigItemMapEntry()
    view_id = ConfigItem(name="ViewId", type="string")
    view_id.addText("view1")
    view.addElement(view_id)
    view.addElement(tables)
    views = ConfigItemMapIndexed(name="Views")
    views.addElement(view)
    view_settings = ConfigItemSet(name="ooo:view-settings")
    view_settings.addElement(views)
    return view_settings
