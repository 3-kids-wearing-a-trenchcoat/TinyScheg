"""
An independent check of a schedule's hard constraints, for the tests and the schedule audit.
It works from the input and the slots alone and reuses nothing from tinyscheg.csp, so that a bug there can't hide
the same bug here.
"""
import itertools
from collections.abc import Sequence

from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.shift import Slot
from tinyscheg.model.shift_generation import all_slots, generate_shifts
from tinyscheg.timing.datetime_range import DateTimeRange


def hard_constraint_violations(schedule_input: ScheduleInput, slots: Sequence[Slot],
                               assignment: Sequence[int | None]) -> list[str]:
    """
    Check every hard constraint of a schedule, including the minimum rest after each worker's history shifts
    :param schedule_input: ScheduleInput the schedule was made for
    :param slots: the schedule's slots (of its own period), in stable order
    :param assignment: a worker index (into schedule_input.workers) per slot
    :return: one message per violation; empty if the schedule is legal
    """
    workers = schedule_input.workers
    min_rest = schedule_input.settings.min_rest
    if len(assignment) != len(slots):
        return [f"{len(assignment)} assignments for {len(slots)} slots"]
    violations = []
    for slot, worker_index in zip(slots, assignment):
        if worker_index is None:
            violations.append(f"slot {slot.index} is unfilled")
            continue
        worker = workers[worker_index]
        if slot.role != "any" and slot.role not in worker.roles:
            violations.append(f"slot {slot.index}: {worker.name} lacks role {slot.role!r}")
        if any(away.start < slot.time.end and slot.time.start < away.end for away in worker.unavailable):
            violations.append(f"slot {slot.index}: {worker.name} is unavailable")
    for first, second in itertools.combinations(range(len(slots)), 2):
        if assignment[first] is None or assignment[first] != assignment[second]:
            continue
        earlier, later = sorted((slots[first].time, slots[second].time))
        if later.start - earlier.end < min_rest:  # negative when they overlap
            violations.append(f"slots {first} and {second}: {workers[assignment[first]].name} rests less than "
                              f"{min_rest} between them")
    for time, name in history_shifts(schedule_input):
        for slot, worker_index in zip(slots, assignment):
            if worker_index is not None and workers[worker_index].name == name:
                earlier, later = sorted((time, slot.time))
                if later.start - earlier.end < min_rest:
                    violations.append(f"slot {slot.index}: {name} rests less than {min_rest} after their history "
                                      f"shift ending {time.end.isoformat()}")
    return violations


def history_shifts(schedule_input: ScheduleInput) -> list[tuple[DateTimeRange, str]]:
    """Every shift worked in the input's history, as (time, worker name), from each previous input and assignment."""
    result = []
    for previous in schedule_input.history:
        names = [worker.name for worker in previous.schedule_input.workers]
        period = previous.schedule_input.settings.period
        for slot in all_slots(generate_shifts(previous.schedule_input.posts, period)):
            result.append((slot.time, names[previous.assignment[slot.index]]))
    return result
