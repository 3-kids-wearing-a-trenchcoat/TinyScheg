"""Validation rules that span several input entries, and the error reporting invalid input."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Iterable, Sequence

from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.worker import NAME_SEPARATOR, Worker


class InputError(ValueError):
    """Invalid input. Holds every problem found, each one naming where in the input it is."""

    def __init__(self, problems: Sequence[str]) -> None:
        """
        :param problems: one message per problem, in input order
        """
        self.problems = tuple(problems)
        super().__init__("invalid input:\n" + "\n".join(f"  - {problem}" for problem in self.problems))


def location(kind: str, index: int, name: object = None) -> str:
    """
    Describe where an entry is in the input, for error messages
    :param kind: str, the kind of entry, e.g. "worker" or "variation"
    :param index: int, the entry's 0-based position in its list
    :param name: the entry's name, if known
    :return: e.g. 'worker #3 ("Jeff")'; positions are shown 1-based
    """
    if isinstance(name, str):
        return f'{kind} #{index + 1} ("{name}")'
    return f"{kind} #{index + 1}"


def validate(schedule_input: ScheduleInput) -> None:
    """
    Check the rules that span several entries of a structurally valid input
    :param schedule_input: ScheduleInput
    :return: None; raises InputError listing every problem found
    """
    problems = find_problems(schedule_input)
    if problems:
        raise InputError(problems)


def find_problems(schedule_input: ScheduleInput) -> list[str]:
    """
    Find every violation of the rules that span several entries
    :param schedule_input: ScheduleInput
    :return: list of problem messages, in input order (empty if the input is valid)
    """
    workers, posts = schedule_input.workers, schedule_input.posts
    problems = _duplicate_names("worker", [worker.name for worker in workers])
    problems += _duplicate_names("post", [post.name for post in posts])
    worker_names = {worker.name for worker in workers}
    for index, worker in enumerate(workers):
        where = location("worker", index, worker.name)
        if NAME_SEPARATOR in worker.name:
            problems.append(f'{where}: names must not contain "{NAME_SEPARATOR}", which joins names in the output')
        problems += _preference_problems(where, worker, worker_names)
    for index, post in enumerate(posts):
        where = location("post", index, post.name)
        for first in range(len(post.variations)):
            for second in range(first + 1, len(post.variations)):
                first_window, second_window = post.variations[first].window, post.variations[second].window
                if first_window.overlaps(second_window):
                    problems.append(f"{where}: variation #{first + 1} ({first_window}) and variation #{second + 1} "
                                    f"({second_window}) overlap")
    return problems + _history_problems(schedule_input)


def _history_problems(schedule_input: ScheduleInput) -> list[str]:
    """
    The history's periods must be the past (ADR 0029): each ends by the time the current period starts, and no two
    overlap
    """
    problems = []
    start = schedule_input.settings.period.start
    history = schedule_input.history
    for index, previous in enumerate(history):
        where = location("history entry", index, previous.source)
        period = previous.schedule_input.settings.period
        if period.end > start:
            problems.append(f"{where}: its period ({_shown(period.start)} to {_shown(period.end)}) must end by the "
                            f"time this schedule's starts ({_shown(start)})")
        for other in range(index):
            if period.overlaps(history[other].schedule_input.settings.period):
                problems.append(f"{where}: its period overlaps that of history entry #{other + 1}")
    return problems


def history_warnings(schedule_input: ScheduleInput) -> list[str]:
    """
    Warnings about the history that don't stop a run: workers of a previous schedule who aren't in this input
    (they've left), whose history is ignored
    :param schedule_input: ScheduleInput
    :return: one message per previous schedule with such workers, in input order
    """
    names = {worker.name for worker in schedule_input.workers}
    warnings = []
    for index, previous in enumerate(schedule_input.history):
        gone = [worker.name for worker in previous.schedule_input.workers if worker.name not in names]
        if gone:
            listed = ", ".join(f'"{name}"' for name in gone)
            warnings.append(f"{location('history entry', index, previous.source)}: {listed} "
                            f"{'is' if len(gone) == 1 else 'are'} not in this input; their history is ignored")
    return warnings


def _shown(moment: dt.datetime) -> str:
    """A moment for messages."""
    return f"{moment:%Y-%m-%d %H:%M}"


def _duplicate_names(kind: str, names: Iterable[str]) -> list[str]:
    """One problem per name that appears more than once, in order of first appearance."""
    counts = Counter(names)
    return [f'{kind} name "{name}" is used {count} times; names must be unique'
            for name, count in counts.items() if count > 1]


def _preference_problems(where: str, worker: Worker, worker_names: set[str]) -> list[str]:
    """
    Check that a worker's likes and dislikes name other existing workers, and don't name the same worker twice
    :param where: str, the worker's location for messages
    :param worker: Worker
    :param worker_names: set of all workers' names
    :return: list of problem messages
    """
    problems = []
    for field, names in (("likes", worker.likes), ("dislikes", worker.dislikes)):
        for name in sorted(names):  # sets have no stable order; sorting keeps messages deterministic
            if name == worker.name:
                problems.append(f'{where}, {field}: a worker can\'t list themselves')
            elif name not in worker_names:
                problems.append(f'{where}, {field}: unknown worker "{name}"')
    for name in sorted(worker.likes & worker.dislikes):
        problems.append(f'{where}: "{name}" is in both likes and dislikes')
    return problems
