"""
Reading a written CSV schedule back, for the tests and the schedule audit.
It lists the shifts with tinyscheg.model alone and reuses nothing from tinyscheg.csp or tinyscheg.scoring.
"""
import csv
import pathlib
from dataclasses import dataclass

from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.shift import Shift, Slot
from tinyscheg.model.shift_generation import all_slots, generate_shifts
from tinyscheg.model.worker import NAME_SEPARATOR
from tinyscheg.output.csv_writer import CSV_ENCODING


@dataclass(frozen=True, slots=True)
class ReadSchedule:
    """A schedule read back: its shifts and slots in stable order, and a worker index per slot."""
    shifts: tuple[Shift, ...]
    slots: tuple[Slot, ...]
    assignment: tuple[int, ...]


class ScheduleReadError(ValueError):
    """The file doesn't match the input: a missing post or shift row, a wrong number of names, or an unknown name."""


def read_schedule(csv_path: pathlib.Path, schedule_input: ScheduleInput) -> ReadSchedule:
    """
    Read a written CSV schedule back: each shift's names, from the row where it starts in its post's column
    :param csv_path: pathlib.Path of the CSV schedule
    :param schedule_input: ScheduleInput the schedule was made for
    :return: the ReadSchedule
    """
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    slots = all_slots(shifts)
    with open(csv_path, encoding=CSV_ENCODING, newline="") as file:
        header, *rows = list(csv.reader(file))
    row_by_start = {row[0]: row for row in rows}
    worker_index = {worker.name: index for index, worker in enumerate(schedule_input.workers)}
    assignment: list[int] = [-1] * len(slots)
    for shift in shifts:
        cell = _cell(header, row_by_start, shift)
        names = cell.split(NAME_SEPARATOR)
        if len(names) != len(shift.slots):
            raise ScheduleReadError(f"{shift.post.name} at {shift.time.start.isoformat()}: expected "
                                    f"{len(shift.slots)} names, got {cell!r}")
        for slot, name in zip(shift.slots, names):
            if name not in worker_index:
                raise ScheduleReadError(f"{shift.post.name} at {shift.time.start.isoformat()}: unknown worker "
                                        f"{name!r}")
            assignment[slot.index] = worker_index[name]
    return ReadSchedule(shifts, slots, tuple(assignment))


def _cell(header: list[str], row_by_start: dict[str, list[str]], shift: Shift) -> str:
    """The text of the cell where a shift starts, in its post's column."""
    start = shift.time.start.isoformat()
    if shift.post.name not in header:
        raise ScheduleReadError(f"no column for post {shift.post.name!r}")
    if start not in row_by_start:
        raise ScheduleReadError(f"no row starting at {start}")
    return row_by_start[start][header.index(shift.post.name)]
