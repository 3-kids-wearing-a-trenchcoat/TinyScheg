"""Choosing an output format by file extension, and writing the grid in it (ADR 0019)."""
from __future__ import annotations

import pathlib
from collections.abc import Callable

from tinyscheg.output.csv_writer import write_csv
from tinyscheg.output.grid import Grid
from tinyscheg.output.xlsx_writer import write_xlsx

Writer = Callable[[Grid, pathlib.Path], None]

# Supported formats by file extension; ODS is planned (see the roadmap)
WRITERS: dict[str, Writer] = {".csv": write_csv, ".xlsx": write_xlsx}
DEFAULT_EXTENSION = ".csv"


class UnsupportedFormatError(ValueError):
    """An output path whose extension isn't a supported format."""


def writer_for(path: str | pathlib.Path) -> Writer:
    """
    Find the writer for an output path
    :param path: the output file's path; its extension (in any case) decides the format
    :return: the writer; raises UnsupportedFormatError naming the supported extensions if there's none
    """
    extension = pathlib.Path(path).suffix.lower()
    if extension not in WRITERS:
        shown = f'"{extension}"' if extension else "(no extension)"
        raise UnsupportedFormatError(f"unsupported output format {shown} (supported: {', '.join(WRITERS)})")
    return WRITERS[extension]


def write_schedule(grid: Grid, path: str | pathlib.Path) -> None:
    """
    Write a grid in the format its path's extension names
    :param grid: Grid
    :param path: the output file's path; the file is replaced if it exists
    :return: None; raises UnsupportedFormatError if the extension isn't supported
    """
    writer_for(path)(grid, pathlib.Path(path))
