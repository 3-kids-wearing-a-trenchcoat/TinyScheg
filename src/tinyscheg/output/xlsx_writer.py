"""Writing the grid as an Excel workbook (ADR 0019), with openpyxl."""
from __future__ import annotations

import pathlib

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from tinyscheg.output.grid import Grid, Span

TIME_HEADERS = ("start", "end")        # the header of the two time columns, before the posts
SHEET_TITLE = "schedule"
DATETIME_FORMAT = "yyyy-mm-dd hh:mm"   # how time cells are shown; they hold real date-time values
TIME_COLUMN_WIDTH = 17                 # in characters, enough for DATETIME_FORMAT
MIN_POST_COLUMN_WIDTH = 10             # in characters
COLUMN_PADDING = 2                     # characters added to the longest text in a post column
CELL_ALIGNMENT = Alignment(vertical="center")  # merged cells show their text in the middle of the block


def write_xlsx(grid: Grid, path: str | pathlib.Path) -> None:
    """
    Write a grid as an Excel workbook
    :param grid: Grid
    :param path: the file to write; it's replaced if it exists
    :return: None. One sheet: a bold header row of start, end, then the post names, frozen with the time columns;
    times as date-time cells; a shift covering several rows as one merged cell; an inactive post's cells empty
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_TITLE
    first_post_column = len(TIME_HEADERS) + 1  # columns and rows are 1-based in openpyxl
    sheet.append([*TIME_HEADERS, *grid.columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row_index, row in enumerate(grid.rows, start=2):
        for column, moment in enumerate((row.start, row.end), start=1):
            cell = sheet.cell(row=row_index, column=column, value=moment)
            cell.number_format = DATETIME_FORMAT
    spans = grid.spans()
    for span in spans:  # each shift's names once, in the first cell of its block, then merged
        row, column = span.first_row + 2, span.column + first_post_column
        cell = sheet.cell(row=row, column=column, value=grid.shift_names[span.shift_index])
        cell.alignment = CELL_ALIGNMENT
        if span.last_row > span.first_row:
            sheet.merge_cells(start_row=row, start_column=column, end_row=span.last_row + 2, end_column=column)
    _set_widths(sheet, grid, spans, first_post_column)
    sheet.freeze_panes = sheet.cell(row=2, column=first_post_column)
    workbook.save(path)


def _set_widths(sheet: Worksheet, grid: Grid, spans: tuple[Span, ...], first_post_column: int) -> None:
    """Set the column widths: the time columns' fixed, each post's to its longest text, with padding."""
    for column in range(1, first_post_column):
        sheet.column_dimensions[get_column_letter(column)].width = TIME_COLUMN_WIDTH
    for index, name in enumerate(grid.columns):
        texts = [name, *(grid.shift_names[span.shift_index] for span in spans if span.column == index)]
        width = max(MIN_POST_COLUMN_WIDTH, max(len(text) for text in texts) + COLUMN_PADDING)
        sheet.column_dimensions[get_column_letter(first_post_column + index)].width = width
