"""Writing the grid as CSV (ADR 0019)."""
from __future__ import annotations

import csv
import pathlib

from tinyscheg.output.grid import Grid

# UTF-8 with a byte order mark, so that Excel recognizes the encoding and shows names in any script correctly
CSV_ENCODING = "utf-8-sig"


def write_csv(grid: Grid, path: str | pathlib.Path) -> None:
    """
    Write a grid as CSV
    :param grid: Grid
    :param path: the file to write; it's replaced if it exists
    :return: None. The header row is start, end, then the post names; times are ISO 8601, and a shift covering
    several rows has its names repeated in each
    """
    with open(path, "w", encoding=CSV_ENCODING, newline="") as file:  # the csv module handles line endings itself
        writer = csv.writer(file)
        writer.writerow(["start", "end", *grid.columns])
        for row_index, row in enumerate(grid.rows):
            writer.writerow([row.start.isoformat(), row.end.isoformat(),
                             *(grid.text(row_index, column) for column in range(len(grid.columns)))])
