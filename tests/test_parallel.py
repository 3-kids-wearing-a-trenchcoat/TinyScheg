"""Tests for tinyscheg.csp.parallel (ADR 0041): branch and bound in parallel processes, with the sequential result."""
import pathlib
import random
import sys
import time

import pytest

from schedule_checker import hard_constraint_violations
from test_cli import SMALL, write
from test_history_search import ANNE, BOB, constants_for, previous, schedule
from test_search import constants_of, small_inputs
from tinyscheg.cli import EXIT_SUCCESS, EXIT_USAGE, main
from tinyscheg.csp import parallel
from tinyscheg.csp.parallel import cut_tree, find_best_schedule_in_parallel
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import SearchProgress, SearchResult, find_best_schedule
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.scoring.penalty import Penalty, score

PROCESSES = 3
FEW_SUBTREES_PER_PROCESS = 4   # so that even small inputs are cut into many subtrees
STRESS_SEEDS = 3
STRESS_DELAY_SECONDS = 0.01    # the longest random delay before a subtree, to shake the processes' timing
SHARE_TOLERANCE = 1e-9

# The tests patch the module before the processes are started; forked processes inherit the patches
forked = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the patches reach only forked processes")

# a history, and a longer new period for four workers, one of them new: something to search in parallel
WITH_HISTORY = schedule(12, 40, workers=("Anne", "Bob", "Cy", "Dan"),
                        history=(previous(0, 12, (ANNE, BOB, ANNE)),))


_stress = {"seed": 0}
_search_subtree = parallel._search_subtree


def _delayed_search_subtree(task: tuple[int, tuple[tuple[int, int], ...], float]) -> parallel._SubtreeResult:
    """Search a subtree after a random delay (at module level, so that the processes can be handed it by name)."""
    time.sleep(random.Random(_stress["seed"] * 1000 + task[0]).random() * STRESS_DELAY_SECONDS)
    return _search_subtree(task)


def same_result(parallel_result: SearchResult, sequential: SearchResult) -> bool:
    """The same schedule and penalty, or, with none, the same point where the search got stuck."""
    if sequential.assignment is None:
        return (parallel_result.assignment is None and parallel_result.deepest == sequential.deepest
                and parallel_result.stuck_slot == sequential.stuck_slot)
    return (parallel_result.assignment, parallel_result.penalty) == (sequential.assignment, sequential.penalty)


@forked
@pytest.mark.parametrize("schedule_input", small_inputs())
def test_the_parallel_search_finds_the_sequential_result(schedule_input: ScheduleInput,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallel, "SUBTREES_PER_PROCESS", FEW_SUBTREES_PER_PROCESS)
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    assert same_result(find_best_schedule_in_parallel(problem, constants, PROCESSES),
                       find_best_schedule(problem, constants))


@forked
def test_with_a_history() -> None:
    problem, constants = build_problem(WITH_HISTORY), constants_for(WITH_HISTORY)
    result = find_best_schedule_in_parallel(problem, constants, PROCESSES)
    assert same_result(result, find_best_schedule(problem, constants))
    assert result.assignment is not None and result.assignment[:3] == (ANNE, BOB, ANNE)


@forked
@pytest.mark.parametrize("seed", range(STRESS_SEEDS))
def test_the_result_doesnt_depend_on_the_processes_timing(seed: int, monkeypatch: pytest.MonkeyPatch) -> None:
    # every process reads the shared best at every node, and each subtree starts after a random delay
    monkeypatch.setattr(parallel, "SUBTREES_PER_PROCESS", FEW_SUBTREES_PER_PROCESS)
    monkeypatch.setattr(parallel, "SHARE_INTERVAL_NODES", 1)
    monkeypatch.setitem(_stress, "seed", seed)
    monkeypatch.setattr(parallel, "_search_subtree", _delayed_search_subtree)
    for schedule_input in small_inputs()[:5] + [WITH_HISTORY]:
        problem = build_problem(schedule_input)
        constants = constants_for(schedule_input) if schedule_input.history else constants_of(schedule_input)
        assert same_result(find_best_schedule_in_parallel(problem, constants, PROCESSES),
                           find_best_schedule(problem, constants))


@forked
def test_progress_rises_to_one_and_each_report_is_a_better_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallel, "SUBTREES_PER_PROCESS", FEW_SUBTREES_PER_PROCESS)
    monkeypatch.setattr(parallel, "POLL_SECONDS", 0.001)
    problem, constants = build_problem(WITH_HISTORY), constants_for(WITH_HISTORY)
    progress: list[SearchProgress] = []
    better: list[Penalty] = []
    result = find_best_schedule_in_parallel(problem, constants, PROCESSES, on_improvement=better.append,
                                            on_progress=progress.append)
    shares = [report.finished for report in progress]
    assert shares == sorted(shares) and shares[-1] == pytest.approx(1.0, abs=SHARE_TOLERANCE)
    totals = [penalty.total for penalty in better]
    assert totals == sorted(totals, reverse=True) and len(set(totals)) == len(totals)
    assert result.penalty is not None and totals[-1] == result.penalty.total


@forked
def test_ctrl_c_keeps_the_best_schedule_found_so_far(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallel, "SUBTREES_PER_PROCESS", FEW_SUBTREES_PER_PROCESS)
    problem, constants = build_problem(WITH_HISTORY), constants_for(WITH_HISTORY)

    def interrupt(penalty: Penalty) -> None:
        raise KeyboardInterrupt

    result = find_best_schedule_in_parallel(problem, constants, PROCESSES, on_improvement=interrupt,
                                            keep_best_on_interrupt=True)
    assert not result.complete and result.assignment is not None
    assert result.penalty == score(constants, result.assignment)
    new = [result.assignment[slot.index] for slot in problem.new_slots]
    assert hard_constraint_violations(WITH_HISTORY, problem.new_slots, new) == []
    with pytest.raises(KeyboardInterrupt):
        find_best_schedule_in_parallel(problem, constants, PROCESSES, on_improvement=interrupt)


def test_one_process_is_the_sequential_search() -> None:
    schedule_input = small_inputs()[0]
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    assert find_best_schedule_in_parallel(problem, constants, 1) == find_best_schedule(problem, constants)


@pytest.mark.parametrize("schedule_input", small_inputs()[:5])
def test_the_subtrees_shares_and_the_branches_above_them_add_up_to_the_whole(schedule_input: ScheduleInput) -> None:
    problem, constants = build_problem(schedule_input), constants_of(schedule_input)
    cutting = cut_tree(problem, constants, FEW_SUBTREES_PER_PROCESS * PROCESSES)
    shares = cutting.finished
    for _, share in cutting.cut:
        shares += share
    assert shares == pytest.approx(1.0, abs=SHARE_TOLERANCE)
    paths = [path for path, _ in cutting.cut]
    # no subtree inside another, and in the sequential search's order: paths compare as it visits them
    assert all(first[:len(second)] != second and second[:len(first)] != first
               for index, first in enumerate(paths) for second in paths[index + 1:])


@forked
def test_command_line_jobs(tmp_path: pathlib.Path) -> None:
    input_path = write(tmp_path, SMALL)
    alone, together = tmp_path / "alone.csv", tmp_path / "together.csv"
    assert main([str(input_path), "-o", str(alone), "--jobs", "1"]) == EXIT_SUCCESS
    assert main([str(input_path), "-o", str(together), "-j", "2"]) == EXIT_SUCCESS
    assert alone.read_bytes() == together.read_bytes()
    with pytest.raises(SystemExit) as exit_info:
        main([str(input_path), "--jobs", "0"])
    assert exit_info.value.code == EXIT_USAGE


def test_the_default_is_one_process_per_physical_core(monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR 0043: psutil's count of physical cores, or the operating system's count of processors if it can't tell
    monkeypatch.setattr(parallel.psutil, "cpu_count", lambda logical=True: 6 if not logical else 12)
    assert parallel.default_processes() == 6
    monkeypatch.setattr(parallel.psutil, "cpu_count", lambda logical=True: None)
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 12)
    assert parallel.default_processes() == 12
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: None)
    assert parallel.default_processes() == 1
