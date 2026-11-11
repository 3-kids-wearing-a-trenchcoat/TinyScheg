"""
The command-line interface: read an input file, search for a schedule and write it.
Usage: python src/main.py INPUT [-o OUTPUT]
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
from collections.abc import Callable, Sequence

from tinyscheg.csp.problem import Problem, build_problem, unfillable_slots
from tinyscheg.csp.search import SearchResult, find_best_schedule
from tinyscheg.model.shift import Slot
from tinyscheg.output.grid import build_grid
from tinyscheg.output.writers import DEFAULT_EXTENSION, UnsupportedFormatError, write_schedule, writer_for
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.validation import InputError
from tinyscheg.scoring.constants import build_constants
from tinyscheg.scoring.penalty import Penalty

EXIT_SUCCESS = 0
EXIT_NO_SCHEDULE = 1   # the input is valid, but no legal schedule exists
EXIT_USAGE = 2         # invalid arguments or input (argparse uses 2 as well)
EXIT_INTERRUPTED = 130  # the conventional code for a program stopped with Ctrl+C

PROGRAM = "tinyscheg"
PENALTY_DECIMALS = 2  # how many decimals of the penalty are shown
ELAPSED_DECIMALS = 0  # how many decimals of the seconds elapsed are shown in progress lines


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run TinyScheg from the command line
    :param argv: the arguments, without the program name; None means sys.argv[1:]
    :return: the exit code: 0 if a schedule was written, 1 if no legal schedule exists, 2 for invalid arguments or
    input, 130 if interrupted. Nothing is written unless a schedule was found.
    """
    arguments = _parser().parse_args(argv)
    input_path = pathlib.Path(arguments.input)
    output_path = pathlib.Path(arguments.output) if arguments.output else default_output_path(input_path)
    try:
        return _run(input_path, output_path)
    except KeyboardInterrupt:
        _error("interrupted; no schedule written")
        return EXIT_INTERRUPTED


def default_output_path(input_path: pathlib.Path) -> pathlib.Path:
    """The output path used when none is given: next to the input, named after it, e.g. week1_schedule.csv."""
    return input_path.with_name(f"{input_path.stem}_schedule{DEFAULT_EXTENSION}")


def _parser() -> argparse.ArgumentParser:
    """The command-line argument parser."""
    parser = argparse.ArgumentParser(prog=PROGRAM, description="Create a fair shift schedule from an input file.")
    parser.add_argument("input", help="the YAML input file")
    parser.add_argument("-o", "--output",
                        help=f"the schedule file to write; its extension sets the format (default: next to the "
                             f"input, named <input name>_schedule{DEFAULT_EXTENSION})")
    return parser


def _run(input_path: pathlib.Path, output_path: pathlib.Path) -> int:
    """
    Read, search and write, reporting any problem on standard error
    :param input_path: pathlib.Path of the input file
    :param output_path: pathlib.Path of the schedule file to write
    :return: the exit code
    """
    try:
        writer_for(output_path)  # checked first, so that a long search doesn't end in a typo
        schedule_input = read_input(input_path)
    except (UnsupportedFormatError, InputError) as exc:
        _error(str(exc))
        return EXIT_USAGE
    except OSError as exc:
        _error(f"can't read {input_path}: {exc.strerror or exc}")
        return EXIT_USAGE

    problem = build_problem(schedule_input)
    unfillable = unfillable_slots(problem)
    if unfillable:
        _error("no legal schedule exists:\n" + "\n".join(f"  - no worker can fill {describe_slot(slot)}"
                                                          for slot in unfillable))
        return EXIT_NO_SCHEDULE
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    result = find_best_schedule(problem, constants, on_improvement=_progress_reporter())
    if result.assignment is None or result.penalty is None:
        _error(_describe_failure(problem, result))
        return EXIT_NO_SCHEDULE

    grid = build_grid(schedule_input.posts, problem.shifts, problem.workers, result.assignment)
    try:
        write_schedule(grid, output_path)
    except OSError as exc:
        _error(f"can't write {output_path}: {exc.strerror or exc}")
        return EXIT_USAGE
    print(f"wrote {output_path}: {len(problem.shifts)} shifts, {len(problem.slots)} slots, "
          f"{len(problem.workers)} workers")
    print(f"{describe_penalty(result.penalty)}, the best possible")
    return EXIT_SUCCESS


def _progress_reporter() -> Callable[[Penalty], None]:
    """A function that reports each better schedule the search finds on standard error, with the time it took."""
    started = time.perf_counter()

    def report(penalty: Penalty) -> None:
        elapsed = time.perf_counter() - started
        _error(f"found penalty {penalty.total:.{PENALTY_DECIMALS}f} after {elapsed:.{ELAPSED_DECIMALS}f} s")
    return report


def describe_penalty(penalty: Penalty) -> str:
    """A penalty for messages, e.g. 'penalty 2.84 (likes 0.31, workload 4.62, rest 0.12)'; lower is better."""
    def shown(value: float) -> str:
        return f"{value:.{PENALTY_DECIMALS}f}"
    return (f"penalty {shown(penalty.total)} (likes {shown(penalty.likes)}, workload {shown(penalty.workload)}, "
            f"rest {shown(penalty.rest)})")


def describe_slot(slot: Slot) -> str:
    """A slot for messages, e.g. 'desk, 2025-01-02 08:00–12:00 (role "supervisor")'."""
    start, end = slot.time.start, slot.time.end
    end_text = f"{end:%H:%M}" if end.date() == start.date() else f"{end:%Y-%m-%d %H:%M}"
    return f'{slot.post.name}, {start:%Y-%m-%d %H:%M}–{end_text} (role "{slot.role}")'


def _describe_failure(problem: Problem, result: SearchResult) -> str:
    """The message for a search that found no schedule: how far it got, and where it was stuck (ADR 0020)."""
    message = (f"no legal schedule exists; the search filled at most {result.deepest} of {len(problem.slots)} "
               f"slots")
    if result.stuck_slot is not None:
        message += f", and got stuck at {describe_slot(result.stuck_slot)}"
    return message


def _error(message: str) -> None:
    """Print a message on standard error, prefixed with the program's name."""
    print(f"{PROGRAM}: {message}", file=sys.stderr)
