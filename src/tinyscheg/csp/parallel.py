"""
Branch and bound in parallel processes (ADR 0041), with exactly the sequential search's result.

The tree is cut, at the depth giving at least SUBTREES_PER_PROCESS subtrees per process, into subtrees numbered in
the order the sequential search visits them (the tree's shape doesn't depend on the pocket, so the numbering is
fixed). A pool of processes takes them from a queue in that order. The processes share the best schedule found so
far, with the number of the subtree it came from:

* subtree i prunes a branch whose bound is above the best's penalty, or at least it when i comes at or after the
  best's subtree j: an earlier subtree may still tie, and the sequential search would have kept its schedule;
* a complete schedule replaces the best if its penalty is lower, or equal and from an earlier subtree;
* in the end, the best of each subtree (its first found, among equals) is merged by lowest (penalty, subtree).

So the schedule found is the sequential search's own, however the processes' timing falls; only the node counts
differ. Each process reads the shared best into a copy every SHARE_INTERVAL_NODES nodes: a stale copy is never ahead
of the shared one, so it only prunes less. The main process meanwhile reports progress and new bests, and on Ctrl+C
keeps the shared best, as the sequential search does (ADR 0035). It stops the processes by a shared flag, which they
check with the shared best, rather than by killing them: one killed while holding the lock would leave the main
process waiting for it forever.
"""
from __future__ import annotations

import math
import multiprocessing
import os
import signal
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from tinyscheg.csp.problem import Problem
from tinyscheg.csp.search import SearchProgress, SearchResult, _Search, find_best_schedule
from tinyscheg.model.shift import Slot
from tinyscheg.scoring.constants import ScoringConstants
from tinyscheg.scoring.penalty import Penalty, score

# Subtrees per process: enough that a few large early ones don't leave processes idle at the end, few enough that
# setting each one up costs nothing noticeable (2026-11-15: at about 250-1000 subtrees in all, the largest was 1-2% of
# the work and the split cost nothing; at 2000 and more, up to 1.5 times the work on the smallest inputs)
SUBTREES_PER_PROCESS = 32
# How often a process reads the shared best and reports its progress, in nodes
SHARE_INTERVAL_NODES = 4096
# How often the main process reports progress and new bests while it waits, in seconds
POLL_SECONDS = 0.25
NO_SUBTREE = sys.maxsize  # the best's subtree while there is none
# Reading the shared best gives up waiting for its lock after this many seconds, and reads it anyway: only reachable
# if a process was killed holding the lock (a second Ctrl+C), when a slightly stale best is better than none
LOCK_TIMEOUT_SECONDS = 5.0


def default_processes() -> int:
    """The number of processes used unless told otherwise: one per processor the operating system reports."""
    return os.cpu_count() or 1


def find_best_schedule_in_parallel(problem: Problem, constants: ScoringConstants, processes: int,
                                   on_improvement: Callable[[Penalty], None] | None = None,
                                   on_progress: Callable[[SearchProgress], None] | None = None,
                                   keep_best_on_interrupt: bool = False) -> SearchResult:
    """
    find_best_schedule, run by several processes; the same schedule and penalty, however the processes' timing falls
    :param problem: Problem
    :param constants: ScoringConstants, built for the same input
    :param processes: how many processes; 1 runs the sequential search itself
    :param on_improvement: called with the penalty of each better schedule as it's found; None for no calls
    :param on_progress: called with the search's progress every POLL_SECONDS while it runs; None for no calls
    :param keep_best_on_interrupt: True to return the best schedule found so far when Ctrl+C stops the search, marked
    as not complete; False to let KeyboardInterrupt through
    :return: as find_best_schedule; the node counts are those of all processes together
    """
    if processes <= 1:
        return find_best_schedule(problem, constants, on_improvement=on_improvement, on_progress=on_progress,
                                  keep_best_on_interrupt=keep_best_on_interrupt)
    run = _Run(problem, constants, processes, on_improvement, on_progress)
    try:
        return run.search()
    except KeyboardInterrupt:
        if not keep_best_on_interrupt:
            raise
        return run.interrupted()


def cut_tree(problem: Problem, constants: ScoringConstants, target: int) -> _Search:
    """
    Cut the search tree into subtrees, at the first depth giving at least target of them
    :param problem: Problem
    :param constants: ScoringConstants
    :param target: the fewest subtrees wanted
    :return: the cutting run: its cut lists each subtree's path and share in the sequential order; its finished share
    and nodes are those of the branches above the cut (dead ends), and its deepest point is the search's if no subtree
    is left
    """
    depth = 0
    while True:
        depth += 1
        run = _Search(problem, constants)
        run.cut_depth = depth
        run.search()
        reached = max((len(path) for path, _ in run.cut), default=0)
        if len(run.cut) >= target or reached < depth:  # enough, or only complete schedules left above the depth
            return run


class _Stopped(Exception):
    """Raised in a process's search when the main process has asked the processes to stop."""


@dataclass(frozen=True, slots=True)
class _SubtreeResult:
    """What a process found in one subtree."""
    index: int
    best: tuple[float, tuple[int, ...]] | None  # (penalty total, assignment): the subtree's best, its first among equals
    nodes: int
    pruned: int
    deepest: int
    stuck_slot: int | None  # the stuck slot's index


class _Shared:
    """
    What the processes share: the best schedule so far (penalty total and parts, its subtree and its assignment), under
    one lock, and each process's progress (finished share and nodes, each written only by its process)
    """

    def __init__(self, context: Any, slots: int, processes: int) -> None:
        """
        :param context: the multiprocessing context the processes are started with
        :param slots: the number of slots, for the assignment
        :param processes: the number of processes, for their progress
        """
        self.lock = context.Lock()
        self.total = context.Value("d", math.inf, lock=False)
        self.subtree = context.Value("q", NO_SUBTREE, lock=False)
        self.parts = context.Array("d", 3, lock=False)  # likes, workload, rest
        self.assignment = context.Array("q", slots, lock=False)
        self.finished = context.Array("d", processes, lock=False)
        self.nodes = context.Array("q", processes, lock=False)
        self.next_process = context.Value("i", 0, lock=False)
        self.stop = context.Value("i", 0, lock=False)  # set by the main process to stop the processes

    def best(self) -> tuple[float, int]:
        """The best's penalty total and subtree, read together."""
        with self.lock:
            return self.total.value, self.subtree.value

    def offer(self, penalty: Penalty, subtree: int, assignment: Sequence[int]) -> tuple[float, int]:
        """
        Make a complete schedule the best if it beats it: a lower penalty, or an equal one from an earlier subtree
        :return: the best afterwards, its penalty total and subtree
        """
        with self.lock:
            if penalty.total < self.total.value or (penalty.total == self.total.value and subtree < self.subtree.value):
                self.total.value, self.subtree.value = penalty.total, subtree
                self.parts[:] = [penalty.likes, penalty.workload, penalty.rest]
                self.assignment[:] = list(assignment)
            return self.total.value, self.subtree.value

    def best_schedule(self) -> tuple[Penalty, tuple[int, ...]] | None:
        """The best schedule so far and its penalty as shared, or None while there's none."""
        locked = self.lock.acquire(timeout=LOCK_TIMEOUT_SECONDS)
        try:
            if self.total.value == math.inf:
                return None
            likes, workload, rest = self.parts[:]
            return Penalty(self.total.value, likes, workload, rest), tuple(self.assignment[:])
        finally:
            if locked:
                self.lock.release()


# Each process's own state: the problem, the scoring constants, what's shared, which progress slot is its own, and
# its totals over the subtrees it has finished
_process: dict[str, Any] = {}


def _start_process(problem: Problem, constants: ScoringConstants, shared: _Shared) -> None:
    """Set up a process of the pool. Ctrl+C is left to the main process, which stops the pool."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    with shared.lock:
        own = shared.next_process.value
        shared.next_process.value += 1
    _process.update(problem=problem, constants=constants, shared=shared, own=own, finished=0.0, nodes=0)


def _search_subtree(task: tuple[int, tuple[tuple[int, int], ...], float]) -> _SubtreeResult:
    """Search one subtree, in a process of the pool: (its number, its path, its share of the search space)."""
    index, path, share = task
    run = _SubtreeSearch(_process["problem"], _process["constants"], _process["shared"], index)
    if not run.shared.stop.value:
        run.start_from(path)
        try:
            run.search(share)
        except _Stopped:
            pass  # the search was interrupted: what this subtree found so far still counts
    _process["finished"] += run.finished
    _process["nodes"] += run.nodes
    _write_progress(_process["finished"], _process["nodes"])
    best = None if run.subtree_best is None else (run.subtree_best[0].total, run.subtree_best[1])
    stuck = run.stuck_slot.index if run.stuck_slot is not None else None
    return _SubtreeResult(index, best, run.nodes, run.pruned, run.deepest, stuck)


def _write_progress(finished: float, nodes: int) -> None:
    """Write this process's finished share and nodes, over all its subtrees, for the main process to read."""
    own = _process["own"]
    _process["shared"].finished[own] = finished
    _process["shared"].nodes[own] = nodes


class _SubtreeSearch(_Search):
    """The sequential search over one subtree, pruning and keeping schedules against the shared best."""

    def __init__(self, problem: Problem, constants: ScoringConstants, shared: _Shared, subtree: int) -> None:
        """
        :param problem: Problem
        :param constants: ScoringConstants
        :param shared: what the processes share
        :param subtree: the subtree's number in the sequential order
        """
        super().__init__(problem, constants)
        self.shared = shared
        self.subtree = subtree
        self.subtree_best: tuple[Penalty, tuple[int, ...]] | None = None
        self.known = shared.best()  # the shared best's penalty total and subtree, as last read

    def search(self, weight: float = 1.0) -> bool:
        """
        The search, reading the shared best and reporting progress every SHARE_INTERVAL_NODES nodes, and stopping
        (raising _Stopped) if the main process has asked it to
        """
        if self.nodes and self.nodes % SHARE_INTERVAL_NODES == 0:
            if self.shared.stop.value:
                raise _Stopped
            self.known = self.shared.best()
            self.report_progress()
        return super().search(weight)

    def report_progress(self) -> None:
        """Write this process's finished share and nodes so far: its finished subtrees' and this one's so far."""
        _write_progress(_process["finished"] + self.finished, _process["nodes"] + self.nodes)

    def _pocket_total(self) -> float | None:
        """The shared best's penalty, as last read."""
        total = self.known[0]
        return None if total == math.inf else total

    def _ties_lose(self) -> bool:
        """An equal penalty loses unless this subtree comes before the best's."""
        return self.subtree >= self.known[1]

    def _complete(self) -> bool:
        """Keep a complete schedule as this subtree's best if it's the first or better, and offer it to be shared."""
        penalty = score(self.constants, self.state.assigned)
        assignment = tuple(self.state.assigned)
        if self.subtree_best is None or penalty.total < self.subtree_best[0].total:
            self.subtree_best = (penalty, assignment)
        self.known = self.shared.offer(penalty, self.subtree, assignment)
        return False


class _Run:
    """One parallel search, seen from the main process."""

    def __init__(self, problem: Problem, constants: ScoringConstants, processes: int,
                 on_improvement: Callable[[Penalty], None] | None,
                 on_progress: Callable[[SearchProgress], None] | None) -> None:
        """See find_best_schedule_in_parallel."""
        self.problem = problem
        self.constants = constants
        self.processes = processes
        self.on_improvement = on_improvement
        self.on_progress = on_progress
        self.context = multiprocessing.get_context(_start_method())
        self.shared = _Shared(self.context, len(problem.slots), processes)
        self.cutting: _Search | None = None
        self.reported = math.inf  # the best penalty reported so far
        self.results: list[_SubtreeResult] = []

    def search(self) -> SearchResult:
        """Cut the tree, search the subtrees in the pool, and merge what they found."""
        self._progress()
        self.cutting = cut_tree(self.problem, self.constants, SUBTREES_PER_PROCESS * self.processes)
        tasks = [(index, path, share) for index, (path, share) in enumerate(self.cutting.cut)]
        if tasks:
            with self.context.Pool(min(self.processes, len(tasks)), _start_process,
                                   (self.problem, self.constants, self.shared)) as pool:
                outcomes = pool.imap_unordered(_search_subtree, tasks)
                try:
                    while True:
                        try:
                            self.results.append(outcomes.next(POLL_SECONDS))
                        except multiprocessing.TimeoutError:
                            pass
                        except StopIteration:
                            break
                        self._report()
                except KeyboardInterrupt:
                    # ask the processes to stop, and let them finish (each within SHARE_INTERVAL_NODES nodes, and
                    # the subtrees left at once) before the pool is shut down: none is killed holding the lock
                    self.shared.stop.value = 1
                    self.results.extend(outcomes)
                    raise
        self._report()
        return self._merge()

    def interrupted(self) -> SearchResult:
        """The result of a search stopped by Ctrl+C: the best schedule shared so far, with its penalty from scratch."""
        best = self.shared.best_schedule()
        progress = self._totals()
        if best is None:
            return SearchResult(None, 0, None, nodes=progress.nodes, pruned=self._pruned(), complete=False,
                                finished=progress.finished)
        assignment = best[1]
        return SearchResult(assignment, len(self.problem.slots), None, score(self.constants, assignment),
                            progress.nodes, self._pruned(), complete=False, finished=progress.finished)

    def _merge(self) -> SearchResult:
        """The best of the subtrees' bests by (penalty, subtree), or where the search got stuck if there's none."""
        progress = self._totals()
        found = [(result.best[0], result.index, result.best[1]) for result in self.results if result.best is not None]
        if found:
            _, _, assignment = min(found, key=lambda candidate: (candidate[0], candidate[1]))
            return SearchResult(assignment, len(self.problem.slots), None, score(self.constants, assignment),
                                progress.nodes, self._pruned())
        deepest, stuck = self._stuck()
        return SearchResult(None, deepest, stuck, nodes=progress.nodes, pruned=self._pruned())

    def _stuck(self) -> tuple[int, Slot | None]:
        """
        The deepest point and stuck slot, as the sequential search reports them: the first subtree in order to reach
        the greatest depth, or, with no subtrees, the cutting run's (its branches all ended above the cut)
        """
        if not self.results:
            assert self.cutting is not None
            return self.cutting.deepest, self.cutting.stuck_slot
        deepest = max(result.deepest for result in self.results)
        first = min((result for result in self.results if result.deepest == deepest),
                    key=lambda result: result.index)
        return deepest, None if first.stuck_slot is None else self.problem.slots[first.stuck_slot]

    def _report(self) -> None:
        """Report a strictly better shared best, and the progress."""
        best = self.shared.best_schedule()
        if best is not None and best[0].total < self.reported:
            self.reported = best[0].total
            if self.on_improvement is not None:
                self.on_improvement(best[0])
        self._progress()

    def _progress(self) -> None:
        """Report the progress, if anyone's listening."""
        if self.on_progress is not None:
            self.on_progress(self._totals())

    def _totals(self) -> SearchProgress:
        """The share finished and the nodes, of the cutting run and every process together."""
        finished = self.cutting.finished if self.cutting is not None else 0.0
        nodes = self.cutting.nodes if self.cutting is not None else 0
        for value in self.shared.finished[:]:  # a plain loop rounds the same on every interpreter
            finished += value
        for count in self.shared.nodes[:]:
            nodes += count
        return SearchProgress(finished, nodes)

    def _pruned(self) -> int:
        """The branches pruned in the subtrees finished."""
        return sum(result.pruned for result in self.results)


def _start_method() -> str:
    """
    How processes are started: forked on Linux, so that they inherit the main process's state, including a warmed-up
    PyPy just-in-time compiler; spawned elsewhere, where forking isn't available or isn't safe
    """
    return "fork" if sys.platform.startswith("linux") else "spawn"
