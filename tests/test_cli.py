"""Tests for tinyscheg.cli, including the end-to-end test."""
import pathlib
import textwrap

import pytest
from openpyxl import load_workbook

from schedule_checker import hard_constraint_violations
import io
import os

from tinyscheg import cli
from tinyscheg.cli import (EXIT_INTERRUPTED, EXIT_NO_SCHEDULE, EXIT_SUCCESS, EXIT_USAGE, default_output_path,
                           describe_penalty, duration, main, percent)
from tinyscheg.csp import search as search_module
from tinyscheg.csp.search import SearchProgress, SearchResult
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_best_schedule
from tinyscheg.output.writers import WRITERS, UnsupportedFormatError, writer_for
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.schedule_reader import read_schedule
from tinyscheg.scoring.constants import build_constants
from tinyscheg.scoring.penalty import Penalty, score

# small enough for branch and bound to finish at once: 8 slots, 5 workers
SMALL = """
settings:
  time: ["2025-01-01T00:00", "2025-01-01T12:00"]
  min_rest: 2
workers:
  - name: "Anne"
    likes: ["Bob"]
  - name: "Bob"
  - name: "Cy"
    roles: ["supervisor"]
    dislikes: ["Anne"]
  - name: "Dan"
    roles: ["supervisor"]
  - name: "Eve"
posts:
  - name: "front gate"
    roles: {any: 2}
    length: 4
  - name: "desk"
    roles: {supervisor: 1}
    length: 6
"""

# three workers for two back-to-back shifts of two, with an hour's rest: every slot needs a different worker
STUCK = """
settings:
  time: ["2025-01-01T00:00", "2025-01-01T08:00"]
  min_rest: 1
workers:
  - name: "Anne"
  - name: "Bob"
  - name: "Cy"
posts:
  - name: "gate"
    roles: {any: 2}
    length: 4
"""

UNFILLABLE = """
settings:
  time: ["2025-01-01T00:00", "2025-01-01T04:00"]
workers:
  - name: "Anne"
posts:
  - name: "desk"
    roles: {supervisor: 1}
    length: 4
"""


def write(tmp_path: pathlib.Path, text: str, name: str = "input.yml") -> pathlib.Path:
    """Write an input file and return its path."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


# --- end to end ---

def test_end_to_end(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write(tmp_path, SMALL)
    output = tmp_path / "schedule.csv"
    assert main([str(input_path), "-o", str(output)]) == EXIT_SUCCESS
    captured = capsys.readouterr()
    wrote, penalty = captured.out.splitlines()
    assert wrote == f"wrote {output}: 5 shifts, 8 slots, 5 workers"
    schedule_input = read_input(input_path)
    problem = build_problem(schedule_input)
    assignment = read_schedule(output, schedule_input).assignment
    assert hard_constraint_violations(schedule_input, problem.slots, assignment) == []
    # the schedule written is the best one, and the penalty shown is its own
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    best = find_best_schedule(problem, constants)
    assert assignment == best.assignment
    assert penalty == f"{describe_penalty(score(constants, assignment))}, the best possible"
    # each better schedule found is reported on standard error, the last being the one written
    progress = captured.err.splitlines()
    assert progress and all(line.startswith("tinyscheg: found penalty ") for line in progress)
    assert progress[-1].startswith(f"tinyscheg: found penalty {score(constants, assignment).total:.2f} after ")



# --- progress and Ctrl+C (ADR 0035) ---

PENALTY = Penalty(8.38, 2.0, 30.0, 1.0)


def test_ctrl_c_writes_the_best_schedule_found_so_far(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_module, "PROGRESS_INTERVAL_NODES", 1)

    def stop_once_a_schedule_is_found(display: cli._ProgressDisplay, progress: SearchProgress) -> None:
        if display.best is not None:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli._ProgressDisplay, "progress", stop_once_a_schedule_is_found)
    input_path, output = write(tmp_path, SMALL), tmp_path / "schedule.csv"
    assert main([str(input_path), "-o", str(output)]) == EXIT_INTERRUPTED
    wrote, penalty = capsys.readouterr().out.splitlines()
    assert wrote.startswith(f"wrote {output}: ")
    assert penalty.endswith("of the search finished)") and "not proven the best" in penalty
    schedule_input = read_input(input_path)
    problem = build_problem(schedule_input)
    assignment = read_schedule(output, schedule_input).assignment
    assert hard_constraint_violations(schedule_input, problem.slots, assignment) == []


def test_ctrl_c_before_any_schedule_writes_nothing(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_module, "PROGRESS_INTERVAL_NODES", 1)

    def stop(display: cli._ProgressDisplay, progress: SearchProgress) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli._ProgressDisplay, "progress", stop)
    output = tmp_path / "schedule.csv"
    assert main([str(write(tmp_path, SMALL)), "-o", str(output)]) == EXIT_INTERRUPTED
    assert "interrupted before any schedule was found; no schedule written" in capsys.readouterr().err
    assert not output.exists()


def test_plain_progress_lines(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str],
                              monkeypatch: pytest.MonkeyPatch) -> None:
    # not on a terminal: each better schedule on its own line, and a progress line now and then
    monkeypatch.setattr(search_module, "PROGRESS_INTERVAL_NODES", 1)
    monkeypatch.setattr(cli, "PLAIN_PROGRESS_SECONDS", 0)
    assert main([str(write(tmp_path, SMALL)), "-o", str(tmp_path / "schedule.csv")]) == EXIT_SUCCESS
    lines = capsys.readouterr().err.splitlines()
    progress = [line for line in lines if "of the search finished after" in line]
    assert progress and all(line.startswith("tinyscheg: ") and " nodes, " in line for line in progress)
    assert all(line.startswith("tinyscheg: found penalty ") for line in lines if line not in progress)


def test_live_block_is_redrawn_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "REDRAW_SECONDS", 0)
    monkeypatch.setattr(cli.shutil, "get_terminal_size", lambda fallback: os.terminal_size((60, 24)))
    stream = io.StringIO()
    display = cli._ProgressDisplay(stream, live=True, codes=True)
    display.improvement(PENALTY)
    first = stream.getvalue()
    assert cli.CURSOR_UP.format(1) not in first and first.count(cli.CLEAR_LINE) == 2 and "\n" in first
    display.progress(SearchProgress(0.5, 12345))
    second = stream.getvalue()[len(first):]
    assert second.startswith("\r" + cli.CURSOR_UP.format(1))  # back up to the first line, then over it
    display.close(SearchResult(None, 0, None, nodes=20000))
    assert stream.getvalue().endswith("\n")
    final = stream.getvalue().split("\r")[-1]
    for line in final.replace(cli.CURSOR_UP.format(1), "").split("\n"):
        assert len(line.replace(cli.CLEAR_LINE, "")) <= 59  # cut to the terminal's width
    assert display.lines("done")[0].startswith("best:     penalty 8.38 (likes 2.00, workload 30.00, rest 1.00)")
    assert display.lines("done")[1].startswith("progress: 100.0% finished, 20,000 nodes, ")
    assert display.lines("done")[1].endswith(" elapsed, done")


def test_live_line_without_terminal_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "REDRAW_SECONDS", 0)
    stream = io.StringIO()
    display = cli._ProgressDisplay(stream, live=True, codes=False)
    display.improvement(PENALTY)
    display.progress(SearchProgress(0.25, 100))
    assert cli.CLEAR_LINE not in stream.getvalue() and "\n" not in stream.getvalue()
    assert stream.getvalue().count("\r") == 2
    assert stream.getvalue().split("\r")[-1].startswith("25.0% finished, 100 nodes, ")
    assert display.compact_line().endswith(" | best 8.38 after 0:00")


def test_time_left_is_estimated_once_enough_is_finished() -> None:
    display = cli._ProgressDisplay(io.StringIO(), live=False)
    assert display._time_left(0.001, 10) == ", estimating the time left"
    assert display._time_left(0.25, 60) == ", about 3:00 left (rough)"
    assert display._time_left(0.25, 60, " s") == ", about 180 s left (rough)"


def test_duration_and_percent() -> None:
    assert [duration(seconds) for seconds in (7.9, 133, 3723)] == ["0:07", "2:13", "1:02:03"]
    assert [percent(share) for share in (0.372, 1.0000000001)] == ["37.2%", "100.0%"]


def test_end_to_end_xlsx(tmp_path: pathlib.Path) -> None:
    input_path = write(tmp_path, SMALL)
    output = tmp_path / "schedule.xlsx"
    assert main([str(input_path), "-o", str(output)]) == EXIT_SUCCESS
    sheet = load_workbook(output).active
    assert [cell.value for cell in sheet[1]][:2] == ["start", "end"]
    assert sheet.max_row > 1


def test_describe_penalty() -> None:
    assert describe_penalty(Penalty(2.8449, 0.3125, 4.6188, 0.1201)) == (
        "penalty 2.84 (likes 0.31, workload 4.62, rest 0.12)")


def test_default_output_is_next_to_the_input(tmp_path: pathlib.Path) -> None:
    input_path = write(tmp_path, SMALL, "week1.yml")
    assert default_output_path(input_path) == tmp_path / "week1_schedule.csv"
    assert main([str(input_path)]) == EXIT_SUCCESS
    assert (tmp_path / "week1_schedule.csv").exists()


def test_existing_output_is_overwritten(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "schedule.csv"
    output.write_text("old", encoding="utf-8")
    assert main([str(write(tmp_path, SMALL)), "-o", str(output)]) == EXIT_SUCCESS
    assert output.read_text(encoding="utf-8-sig").startswith("start,end,front gate,desk")


# --- failures write nothing ---

def test_unsupported_format_is_checked_first(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "schedule.txt"
    assert main([str(tmp_path / "missing.yml"), "-o", str(output)]) == EXIT_USAGE
    assert f'unsupported output format ".txt" (supported: {", ".join(WRITERS)})' in capsys.readouterr().err
    assert not output.exists()


def test_missing_input(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "missing.yml")]) == EXIT_USAGE
    assert "can't read" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_invalid_input(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write(tmp_path, UNFILLABLE.replace("length: 4", "length: 0"))
    assert main([str(input_path)]) == EXIT_USAGE
    error = capsys.readouterr().err
    assert error.startswith("tinyscheg: invalid input:") and "length: must be more than 0 hours" in error
    assert not default_output_path(input_path).exists()


def test_unfillable_slots_are_listed(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write(tmp_path, UNFILLABLE)
    assert main([str(input_path)]) == EXIT_NO_SCHEDULE
    assert capsys.readouterr().err == ("tinyscheg: no legal schedule exists:\n"
                                       '  - no worker can fill desk, 2025-01-01 00:00–04:00 (role "supervisor")\n')
    assert not default_output_path(input_path).exists()


def test_search_failure_says_where_it_got_stuck(tmp_path: pathlib.Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    input_path = write(tmp_path, STUCK)
    output = tmp_path / "schedule.csv"
    output.write_text("an earlier schedule", encoding="utf-8")
    assert main([str(input_path), "-o", str(output)]) == EXIT_NO_SCHEDULE
    assert capsys.readouterr().err == ("tinyscheg: no legal schedule exists; the search filled at most 2 of 4 slots, "
                                       'and got stuck at gate, 2025-01-01 04:00–08:00 (role "any")\n')
    assert output.read_text(encoding="utf-8") == "an earlier schedule"  # left untouched


# --- writers ---

@pytest.mark.parametrize("name", ["schedule.CSV", "schedule.csv"])
def test_writer_for_ignores_case(name: str) -> None:
    assert writer_for(name) is writer_for("x.csv")


def test_writer_for_no_extension() -> None:
    with pytest.raises(UnsupportedFormatError, match="no extension"):
        writer_for("schedule")
