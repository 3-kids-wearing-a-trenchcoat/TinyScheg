"""
The schedule as a grid of time against post (ADR 0019): the internal table every output format is written from.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass

from tinyscheg.model.post import Post
from tinyscheg.model.shift import Shift
from tinyscheg.model.worker import NAME_SEPARATOR, Worker
from tinyscheg.timing.datetime_range import DateTimeRange


@dataclass(frozen=True, slots=True)
class Grid:
    """
    A schedule as a table: one column per post, one row per interval between shift boundaries.
    cells[row][column] is the index of the shift covering that cell, or None if the post isn't active then; a shift
    covering several rows has its index in each of them, which is what spreadsheet formats merge.
    shift_names[i] is the text shown for shift i: its workers' names in stable slot order, joined with " & ".
    """
    columns: tuple[str, ...]
    rows: tuple[DateTimeRange, ...]
    cells: tuple[tuple[int | None, ...], ...]
    shift_names: tuple[str, ...]

    def text(self, row: int, column: int) -> str:
        """The cell as shown: the names of the workers covering it, or "" if the post isn't active then."""
        shift_index = self.cells[row][column]
        return "" if shift_index is None else self.shift_names[shift_index]

    def spans(self) -> tuple[Span, ...]:
        """
        Each shift's block of cells: the consecutive rows it covers in its column, which spreadsheet formats show as
        one merged cell
        :return: a Span per shift in the grid, by column, then by first row
        """
        result = []
        for column in range(len(self.columns)):
            row = 0
            while row < len(self.rows):
                shift_index = self.cells[row][column]
                last = row
                while (shift_index is not None and last + 1 < len(self.rows)
                       and self.cells[last + 1][column] == shift_index):
                    last += 1
                if shift_index is not None:
                    result.append(Span(column, row, last, shift_index))
                row = last + 1
        return tuple(result)


@dataclass(frozen=True, slots=True)
class Span:
    """A shift's block of cells in a Grid: its column, and the first and last rows it covers (inclusive)."""
    column: int
    first_row: int
    last_row: int
    shift_index: int


def build_grid(posts: Sequence[Post], shifts: Sequence[Shift], workers: Sequence[Worker],
               assignment: Sequence[int]) -> Grid:
    """
    Lay a schedule out as a grid
    :param posts: all posts, in input order; each gets a column, even one with no shifts in the period
    :param shifts: the schedule's shifts, in stable order
    :param workers: all workers, in input order
    :param assignment: a worker index per slot, in stable slot order
    :return: the Grid
    """
    rows = _rows(shifts)
    row_starts = [row.start for row in rows]
    column_of = {post.name: column for column, post in enumerate(posts)}  # post names are unique (validation)
    cells: list[list[int | None]] = [[None] * len(posts) for _ in rows]
    for shift in shifts:
        # Shifts never cross a row boundary, since every shift's start and end is one, so a shift covers the rows
        # from the one starting at its start up to the one ending at its end.
        first_row = bisect.bisect_left(row_starts, shift.time.start)
        last_row = bisect.bisect_left(row_starts, shift.time.end)
        for row in range(first_row, last_row):
            cells[row][column_of[shift.post.name]] = shift.index
    shift_names = tuple(NAME_SEPARATOR.join(workers[assignment[slot.index]].name for slot in shift.slots)
                        for shift in shifts)
    return Grid(columns=tuple(post.name for post in posts),
                rows=rows,
                cells=tuple(tuple(row) for row in cells),
                shift_names=shift_names)


def _rows(shifts: Sequence[Shift]) -> tuple[DateTimeRange, ...]:
    """
    The grid's rows
    :param shifts: all shifts
    :return: the intervals between consecutive shift boundaries over all posts, in time order, leaving out intervals
    no shift covers
    """
    boundaries = sorted({moment for shift in shifts for moment in (shift.time.start, shift.time.end)})
    intervals = [DateTimeRange(start, end) for start, end in zip(boundaries, boundaries[1:])]
    return tuple(interval for interval in intervals if any(shift.time.overlaps(interval) for shift in shifts))
