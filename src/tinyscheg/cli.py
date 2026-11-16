"""
The command-line interface: read an input file, search for a schedule and write it.
Usage: python src/main.py INPUT [-o OUTPUT] [-j JOBS]
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import os
import pathlib
import shutil
import sys
import time
from collections.abc import Sequence
from typing import TextIO

from tinyscheg.csp.next_period import NEXT_PERIOD_CHECK_NODES, NextPeriodCheck, check_next_period, next_period_offset
from tinyscheg.csp.parallel import default_processes, find_best_schedule_in_parallel
from tinyscheg.csp.problem import Problem, build_problem, unfillable_slots
from tinyscheg.csp.search import SearchProgress, SearchResult
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.shift import Slot
from tinyscheg.output.grid import build_grid
from tinyscheg.output.writers import DEFAULT_EXTENSION, UnsupportedFormatError, write_schedule, writer_for
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.validation import InputError, history_warnings
from tinyscheg.scoring.constants import build_constants
from tinyscheg.scoring.penalty import Penalty

EXIT_SUCCESS = 0
EXIT_NO_SCHEDULE = 1   # the input is valid, but no legal schedule exists
EXIT_USAGE = 2         # invalid arguments or input (argparse uses 2 as well)
EXIT_INTERRUPTED = 130  # the conventional code for a program stopped with Ctrl+C

PROGRAM = "tinyscheg"
PENALTY_DECIMALS = 2  # how many decimals of the penalty are shown
ELAPSED_DECIMALS = 0  # how many decimals of the seconds elapsed are shown in progress lines
PERCENT_DECIMALS = 1  # how many decimals of the share of the search finished are shown

# The search's progress (ADR 0035)
REDRAW_SECONDS = 0.25          # on a terminal, the progress block is redrawn at most this often
PLAIN_PROGRESS_SECONDS = 60.0  # not on a terminal, a progress line is printed at most this often
ESTIMATE_MIN_FINISHED = 0.01   # the time left is estimated only once this share of the search is finished
FALLBACK_COLUMNS = 80          # the terminal width assumed when it can't be found
# Terminal codes: move the cursor up n lines, and clear the line it's on
CURSOR_UP = "\x1b[{}A"
CLEAR_LINE = "\x1b[2K"
# Windows console API values, for switching a console to understanding the terminal codes
WINDOWS_STD_ERROR_HANDLE = -12
WINDOWS_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run TinyScheg from the command line
    :param argv: the arguments, without the program name; None means sys.argv[1:]
    :return: the exit code: 0 if a schedule was written, 1 if no legal schedule exists, 2 for invalid arguments or
    input, 130 if interrupted. Nothing is written unless a schedule was found; when the search is interrupted with
    Ctrl+C, the best schedule found so far is written, if there is one (ADR 0035).
    """
    arguments = _parser().parse_args(argv)
    input_path = pathlib.Path(arguments.input)
    output_path = pathlib.Path(arguments.output) if arguments.output else default_output_path(input_path)
    jobs = arguments.jobs if arguments.jobs is not None else default_processes()
    try:
        return _run(input_path, output_path, jobs)
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
    parser.add_argument("-j", "--jobs", type=_positive_int,
                        help=f"how many processes search in parallel (default: one per core, here "
                             f"{default_processes()}); 1 searches in a single process. The schedule is the same "
                             f"either way (ADR 0041)")
    return parser


def _positive_int(text: str) -> int:
    """An argument that must be a whole number of at least 1."""
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a whole number of at least 1, got {text!r}")
    return value


def _run(input_path: pathlib.Path, output_path: pathlib.Path, jobs: int) -> int:
    """
    Read, search and write, reporting any problem on standard error
    :param input_path: pathlib.Path of the input file
    :param output_path: pathlib.Path of the schedule file to write
    :param jobs: how many processes search in parallel (ADR 0041)
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
    for warning in history_warnings(schedule_input):
        _error(f"warning: {warning}")

    problem = build_problem(schedule_input)
    unfillable = unfillable_slots(problem)
    if unfillable:
        _error("no legal schedule exists:\n" + "\n".join(f"  - no worker can fill {describe_slot(slot)}"
                                                          for slot in unfillable))
        return EXIT_NO_SCHEDULE
    # with a history, the whole schedule's settings: its period runs from the history's start (ADR 0031)
    settings = problem.settings or schedule_input.settings
    constants = build_constants(settings, problem.workers, problem.shifts, problem.slots, problem.scoring_domains)
    display = _ProgressDisplay(sys.stderr)
    result = find_best_schedule_in_parallel(problem, constants, jobs, on_improvement=display.improvement,
                                            on_progress=display.progress, keep_best_on_interrupt=True)
    display.close(result)
    if result.assignment is None or result.penalty is None:
        if not result.complete:
            _error("interrupted before any schedule was found; no schedule written")
            return EXIT_INTERRUPTED
        _error(_describe_failure(problem, result))
        return EXIT_NO_SCHEDULE

    grid = build_grid(schedule_input.posts, problem.new_shifts, problem.workers, result.assignment)
    try:
        write_schedule(grid, output_path)
    except OSError as exc:
        _error(f"can't write {output_path}: {exc.strerror or exc}")
        return EXIT_USAGE
    print(f"wrote {output_path}: {len(problem.new_shifts)} shifts, {len(problem.new_slots)} slots, "
          f"{len(problem.workers)} workers")
    if not result.complete:
        print(f"{describe_penalty(result.penalty)}, the best found before the search was interrupted, not proven the "
              f"best ({percent(result.finished)} of the search finished)")
        _warn_about_next_period(schedule_input, problem, result.assignment)
        return EXIT_INTERRUPTED
    print(f"{describe_penalty(result.penalty)}, the best possible")
    _warn_about_next_period(schedule_input, problem, result.assignment)
    return EXIT_SUCCESS


class _ProgressDisplay:
    """
    Shows the search's progress on standard error (ADR 0035). On a terminal, a block of two lines redrawn in place:
    the best schedule so far, and the progress (the share of the search finished, nodes, time elapsed and a rough
    time left); one line redrawn with a carriage return where terminal codes can't be used. Otherwise (a file or a
    pipe), each better schedule on its own line, and a progress line now and then.
    """

    def __init__(self, stream: TextIO, live: bool | None = None, codes: bool | None = None) -> None:
        """
        :param stream: where to write, normally standard error
        :param live: True to redraw in place, False for plain lines; None to decide by whether stream is a terminal
        :param codes: whether the terminal understands the codes for redrawing several lines; None to find out
        """
        self.stream = stream
        self.live = stream.isatty() if live is None else live
        self.codes = (self.live and _terminal_codes_work()) if codes is None else codes
        self.started = time.perf_counter()
        self.best: Penalty | None = None
        self.best_found = 0.0                 # seconds into the search when the best schedule was found
        self.latest = SearchProgress(0.0, 0)  # the latest progress reported
        self.last_shown = 0.0                 # when the display was last drawn (or a plain line printed)
        self.drawn = 0                        # how many lines the block currently on screen has (live, with codes)
        self.width = 0                        # how long the line currently on screen is (live, without codes)

    def improvement(self, penalty: Penalty) -> None:
        """Show a better schedule: redraw at once on a terminal, or print a line of its own."""
        self.best, self.best_found = penalty, self._elapsed()
        if self.live:
            self._draw()
        else:
            _error(f"found penalty {penalty.total:.{PENALTY_DECIMALS}f} after "
                   f"{self.best_found:.{ELAPSED_DECIMALS}f} s")

    def progress(self, progress: SearchProgress) -> None:
        """Take the search's latest progress, and show it if it's time to."""
        self.latest = progress
        now = self._elapsed()
        if self.live and now - self.last_shown >= REDRAW_SECONDS:
            self._draw()
        elif not self.live and now - self.last_shown >= PLAIN_PROGRESS_SECONDS:
            self.last_shown = now
            _error(f"{percent(progress.finished)} of the search finished after {now:.{ELAPSED_DECIMALS}f} s, "
                   f"{progress.nodes:,} nodes{self._time_left(progress.finished, now, ' s')}")

    def close(self, result: SearchResult) -> None:
        """Show the final state on a terminal and move below it, so that what's printed next starts a new line."""
        if not self.live:
            return
        self.latest = SearchProgress(result.finished, result.nodes)
        self._draw(ended="done" if result.complete else "interrupted")
        self.stream.write("\n")
        self.stream.flush()

    def lines(self, ended: str | None = None) -> list[str]:
        """
        The block's lines: the best schedule so far, and the progress
        :param ended: what to show instead of the time left once the search has ended ("done" or "interrupted")
        """
        best = (f"{describe_penalty(self.best)}, found after {duration(self.best_found)}" if self.best is not None
                else "none found yet")
        return [f"best:     {best}", f"progress: {self._progress_text(ended)}"]

    def compact_line(self, ended: str | None = None) -> str:
        """The block in one line, the progress first, for terminals where it can't be redrawn as two lines."""
        best = (f"best {self.best.total:.{PENALTY_DECIMALS}f} after {duration(self.best_found)}"
                if self.best is not None else "no schedule yet")
        return f"{self._progress_text(ended)} | {best}"

    def _progress_text(self, ended: str | None) -> str:
        """E.g. '37.2% finished, 1,423,912 nodes, 2:13 elapsed, about 3:40 left (rough)'."""
        now = self._elapsed()
        finished = self.latest.finished
        left = f", {ended}" if ended else self._time_left(finished, now)
        return f"{percent(finished)} finished, {self.latest.nodes:,} nodes, {duration(now)} elapsed{left}"

    def _draw(self, ended: str | None = None) -> None:
        """Redraw the block in place, each line cut to the terminal's width (a wrapped line would break redrawing)."""
        self.last_shown = self._elapsed()
        columns = shutil.get_terminal_size((FALLBACK_COLUMNS, 0)).columns - 1  # the last column can make it wrap
        if self.codes:
            lines = [line[:columns] for line in self.lines(ended)]
            up = "\r" + CURSOR_UP.format(self.drawn - 1) if self.drawn > 1 else "\r"
            self.stream.write(up + "\n".join(CLEAR_LINE + line for line in lines))
            self.drawn = len(lines)
        else:
            line = self.compact_line(ended)[:columns]
            self.stream.write("\r" + line.ljust(self.width))
            self.width = len(line)
        self.stream.flush()

    def _time_left(self, finished: float, now: float, unit: str = "") -> str:
        """', about 3:40 left (rough)', or ', estimating the time left' before enough of the search is finished."""
        if finished < ESTIMATE_MIN_FINISHED:
            return ", estimating the time left"
        left = now * (1 - finished) / finished
        shown = f"{left:.{ELAPSED_DECIMALS}f}{unit}" if unit else duration(left)
        return f", about {shown} left (rough)"

    def _elapsed(self) -> float:
        """Seconds since the search started."""
        return time.perf_counter() - self.started


def _terminal_codes_work() -> bool:
    """
    Whether standard error's terminal understands the codes for moving the cursor and clearing a line: not a "dumb"
    terminal; on Windows, only once the console has been switched to understanding them
    """
    if os.environ.get("TERM") == "dumb":
        return False
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # only on Windows
        handle = kernel32.GetStdHandle(WINDOWS_STD_ERROR_HANDLE)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | WINDOWS_VIRTUAL_TERMINAL_PROCESSING))
    except (AttributeError, OSError):
        return False


def duration(seconds: float) -> str:
    """A duration for progress lines, e.g. '0:07', '2:13' or '1:02:03' (hours, minutes, seconds)."""
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def percent(share: float) -> str:
    """A share as a percentage, e.g. '37.2%'; never above 100%, though rounding can take the sum a hair past 1."""
    return f"{min(share, 1.0) * 100:.{PERCENT_DECIMALS}f}%"


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
    message = (f"no legal schedule exists; the search filled at most {result.deepest} of {len(problem.new_slots)} "
               f"slots")
    if result.stuck_slot is not None:
        message += f", and got stuck at {describe_slot(result.stuck_slot)}"
    return message


def _warn_about_next_period(schedule_input: ScheduleInput, problem: Problem, assignment: Sequence[int]) -> None:
    """
    Warn on standard error if the schedule leaves the next period, with the same parameters, no legal schedule, or
    note that the check couldn't tell (ADR 0042); say nothing if it can be filled
    :param schedule_input: ScheduleInput
    :param problem: its Problem
    :param assignment: the schedule written, a worker index per slot of the problem
    """
    check = check_next_period(schedule_input, problem, assignment)
    if check is NextPeriodCheck.FILLABLE:
        return
    period = schedule_input.settings.period
    offset = next_period_offset(schedule_input)
    following = describe_period(period.start + offset, period.end + offset)
    sys.stdout.flush()  # after the summary on standard output, even when both go to one file
    if check is NextPeriodCheck.NOT_FILLABLE:
        _error(f"warning: after this schedule, the next period with the same parameters ({following}) has no legal "
               f"schedule")
    else:
        _error(f"note: couldn't tell whether the next period with the same parameters ({following}) can still be "
               f"filled after this schedule (the check stopped after {NEXT_PERIOD_CHECK_NODES:,} steps)")


def describe_period(start: dt.datetime, end: dt.datetime) -> str:
    """A period for messages, e.g. '2025-01-02 08:00–2025-01-03 08:00'."""
    return f"{start:%Y-%m-%d %H:%M}–{end:%Y-%m-%d %H:%M}"


def _error(message: str) -> None:
    """Print a message on standard error, prefixed with the program's name."""
    print(f"{PROGRAM}: {message}", file=sys.stderr)
