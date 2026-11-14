"""
Tune the scoring parameters (docs/explanation/tuning.md): for each benchmark input and each parameter setting, find
the best schedule by branch and bound, then continue it for a second period with the first as history and find the
best of that too; audit both, and record measures that don't come from the audit. Each setting's unit trade-offs are
checked against the user's rules too. A development tool.
Usage:
  PYTHONPATH=src python tools/tune.py run STAGE [--jobs N]   run a stage (resumable: finished runs are kept)
  PYTHONPATH=src python tools/tune.py status                 progress and results so far
  PYTHONPATH=src python tools/tune.py report STAGE           each setting's results, best first
  PYTHONPATH=src python tools/tune.py reaudit STAGE          re-audit a finished stage's schedules, after the audit
                                                             changed (no new search; the old file is kept as .bak)
  PYTHONPATH=src python tools/tune.py round NAME --setting PARAM=VALUE,... [--setting ...] [--inputs GROUP]
                                                             run a tuning round: the settings given, on a group of
                                                             inputs (tuning, holdout or confirm), as stage NAME
Stages: baseline (the defaults, on every input), sensitivity (one parameter at a time, on the tuning inputs), and
any number of named rounds.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import multiprocessing
import os
import pathlib
import re
import shutil
import signal
import statistics
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from audit import build_context, evaluate, find_fixes, summarize, with_history
from tinyscheg.csp.problem import Problem, build_problem
from tinyscheg.csp.search import SearchResult, find_best_schedule
from tinyscheg.model.schedule_input import (DEFAULT_LIKES_WEIGHT, DEFAULT_NEUTRAL_PARTNER, DEFAULT_REST_WEIGHT,
                                            DEFAULT_SHIFT_SHARE, DEFAULT_WORKLOAD_POWER, DEFAULT_WORKLOAD_WEIGHT,
                                            PreviousSchedule, ScheduleInput, ScoringParameters)
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.constants import ScoringConstants, build_constants, hours, unavailable_before
from tinyscheg.scoring.penalty import REST_POWER
from tinyscheg.timing.datetime_range import DateTimeRange

BENCHMARKS = pathlib.Path(__file__).parent / "benchmarks"
MANIFEST = BENCHMARKS / "manifest.csv"
RESULTS = BENCHMARKS / "results"
JOB_TIME_LIMIT = 600.0   # seconds; a run taking longer is recorded as timed out, so one setting can't stall a stage
DEFAULT_JOBS = max(1, (os.cpu_count() or 2) - 2)  # parallel runs, leaving a little of the machine free
FIXED_STAGES = ("baseline", "sensitivity")        # every other stage is a named round
ROUND_NAME = re.compile(r"[A-Za-z0-9_-]+")        # a round's name is also its results file's name
INPUT_GROUPS = ("tuning", "holdout", "confirm")   # the inputs a round can run on (see group_inputs)

# sensitivity: each parameter over these values, the others at their defaults
LIKES_SHARES = (0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6)   # the likes weight's share; workload and rest keep their ratio
REST_SHARES = (0.1, 0.2, 0.25, 0.3, 0.4, 0.5)         # the rest weight's share; likes and workload keep theirs
WORKLOAD_POWERS = (2, 3, 4)
NEUTRAL_PARTNERS = (0.1, 0.2, 0.25, 1 / 3, 0.4, 0.45)  # all below 1/2: a dislike outweighs a like (ADR 0023)
SHIFT_SHARES = (0.0, 0.25, 0.5, 0.75, 1.0)            # 0 is hours only, as before ADR 0026

EXAMPLE = pathlib.Path(__file__).parent.parent / "exampleInput.yml"  # the input the unit trade-offs are computed on
AT_MINIMUM_TOLERANCE = 1e-9  # hours: a rest within this of the minimum rest counts as at the minimum
EQUAL_AVAILABILITY_TOLERANCE = 1e-9  # hours: workers this close to the most available one count as fully available
# The user's rules (2026-11-14), checked on each setting's unit trade-offs on the example (the defaults' in
# tests/test_default_tradeoffs.py): an avoidable two-shift gap (an "outrage") must outweigh this many likes or
# dislikes, and one worker resting at the minimum twice; a like or dislike may make up for one short rest, never a
# second one for the same worker; and a like is worth about one short rest, within this factor either way
OUTRAGE_PAIRINGS = 3
LIKE_PER_SHORT_REST_FACTOR = 1.25
RULE_CHECKS = ("outrage_outweighs_pairings", "outrage_outweighs_twice_at_minimum",
               "second_short_rest_outweighs_pairing", "like_about_one_short_rest")  # unit_tradeoffs' checks, in order

AUDIT_FIELDS = ("complaints", "easy_fixes", "easy_fix_severity", "no_fix_severity", "aggrieved", "concentration",
                "separate_complaints", "separate_severity")
# measures that don't come from the audit (rests in available time, ADR 0038; peers are the fully available workers)
MEASURE_FIELDS = ("rests", "rests_at_minimum", "rest_median", "shortest_rest_spread", "peer_hours_gap",
                  "peer_shifts_gap", "liked_pairings", "disliked_pairings")
DAY2 = "day2_"  # the prefix of the second period's fields, measured over both periods together
RESULT_FIELDS = ("stage", "setting", "input", "tier", "holdout", "likes_weight", "workload_weight", "rest_weight",
                 "workload_power", "neutral_partner", "shift_share", "status", "seconds", "nodes",
                 "penalty", "likes", "workload", "rest", *AUDIT_FIELDS, *MEASURE_FIELDS, "assignment",
                 f"{DAY2}status", f"{DAY2}seconds", f"{DAY2}nodes", f"{DAY2}penalty",
                 *(DAY2 + field for field in AUDIT_FIELDS), *(DAY2 + field for field in MEASURE_FIELDS),
                 f"{DAY2}assignment")


@dataclass(frozen=True, slots=True)
class Setting:
    """A named set of scoring parameters (weights before normalizing)."""
    name: str
    likes_weight: float = DEFAULT_LIKES_WEIGHT
    workload_weight: float = DEFAULT_WORKLOAD_WEIGHT
    rest_weight: float = DEFAULT_REST_WEIGHT
    workload_power: int = DEFAULT_WORKLOAD_POWER
    neutral_partner: float = DEFAULT_NEUTRAL_PARTNER
    shift_share: float = DEFAULT_SHIFT_SHARE

    def parameters(self) -> ScoringParameters:
        """The ScoringParameters for this setting."""
        return ScoringParameters(self.likes_weight, self.workload_weight, self.rest_weight, self.workload_power,
                                 self.neutral_partner, self.shift_share)


DEFAULTS = Setting("defaults")


def _with_share(share: float, weight: str) -> dict[str, float]:
    """Weights giving one of them the share asked for, the other two keeping their default ratio."""
    defaults = {"likes_weight": DEFAULT_LIKES_WEIGHT, "workload_weight": DEFAULT_WORKLOAD_WEIGHT,
                "rest_weight": DEFAULT_REST_WEIGHT}
    others = sum(value for name, value in defaults.items() if name != weight)
    return {name: share if name == weight else (1 - share) * value / others for name, value in defaults.items()}


def sensitivity_settings() -> list[Setting]:
    """One parameter at a time over its values, the others at their defaults."""
    settings = [Setting(f"likes share {share:g}", **_with_share(share, "likes_weight")) for share in LIKES_SHARES]
    settings += [Setting(f"rest share {share:g}", **_with_share(share, "rest_weight")) for share in REST_SHARES]
    settings += [Setting(f"workload power {power}", workload_power=power) for power in WORKLOAD_POWERS]
    settings += [Setting(f"neutral partner {value:.3g}", neutral_partner=value) for value in NEUTRAL_PARTNERS]
    settings += [Setting(f"shift share {value:g}", shift_share=value) for value in SHIFT_SHARES]
    return settings


# --- the benchmark inputs ---

@dataclass(frozen=True, slots=True)
class Benchmark:
    """A benchmark input from the manifest."""
    name: str
    tier: str
    holdout: bool

    @property
    def path(self) -> pathlib.Path:
        """Where the input is."""
        return BENCHMARKS / "inputs" / f"{self.name}.yml"


def benchmarks() -> list[Benchmark]:
    """Every benchmark input kept in the manifest, in manifest order."""
    with open(MANIFEST, encoding="utf-8", newline="") as file:
        return [Benchmark(row["name"], row["tier"], row["holdout"] == "True") for row in csv.DictReader(file)
                if row["name"]]


def stage_jobs(stage: str) -> list[tuple[Setting, Benchmark]]:
    """
    The runs of a stage: baseline runs the defaults on every input; sensitivity runs its settings on the tuning
    inputs only (the sweep tier, without the held-back ones)
    """
    if stage == "baseline":
        return [(DEFAULTS, benchmark) for benchmark in benchmarks()]
    return [(setting, benchmark) for setting in sensitivity_settings() for benchmark in group_inputs("tuning")]


def group_inputs(group: str) -> list[Benchmark]:
    """
    A group of benchmark inputs, in manifest order
    :param group: "tuning" (the sweep tier without the held-back inputs), "holdout" (the held-back inputs of every
    tier) or "confirm" (the confirm tier)
    :return: list of Benchmark
    """
    if group == "tuning":
        return [benchmark for benchmark in benchmarks() if benchmark.tier == "sweep" and not benchmark.holdout]
    if group == "holdout":
        return [benchmark for benchmark in benchmarks() if benchmark.holdout]
    if group == "confirm":
        return [benchmark for benchmark in benchmarks() if benchmark.tier == "confirm"]
    raise ValueError(f"unknown input group {group!r}; expected one of {', '.join(INPUT_GROUPS)}")


def parse_setting(text: str) -> Setting:
    """
    A setting from the command line: comma-separated PARAM=VALUE pairs, each PARAM a ScoringParameters field, the
    others at their defaults; named by its pairs in field order, so that the same setting always gets the same name
    :param text: str, e.g. "neutral_partner=0.25,shift_share=0.5"
    :return: Setting
    :raise ValueError: on an unknown parameter, a value of the wrong type or out of range, or a parameter given twice
    """
    fields = [field.name for field in dataclasses.fields(Setting) if field.name != "name"]
    values: dict[str, float | int] = {}
    for pair in filter(None, (part.strip() for part in text.split(","))):
        name, equals, value = pair.partition("=")
        name = name.strip()
        if not equals or name not in fields:
            raise ValueError(f"{pair!r} isn't PARAM=VALUE with PARAM one of {', '.join(fields)}")
        if name in values:
            raise ValueError(f"{name} is given twice")
        kind = type(getattr(DEFAULTS, name))  # int for the workload power, float otherwise
        values[name] = kind(value)
    if not values:
        raise ValueError("a setting needs at least one PARAM=VALUE")
    named = ",".join(f"{name}={values[name]:g}" for name in fields if name in values)
    setting = Setting(named, **values)
    setting.parameters()  # validates the values
    return setting


def round_jobs(settings: list[Setting], group: str) -> list[tuple[Setting, Benchmark]]:
    """The runs of a round: every setting on every input of the group."""
    return [(setting, benchmark) for setting in settings for benchmark in group_inputs(group)]


# --- one run ---

class _TimedOut(Exception):
    """A run went over JOB_TIME_LIMIT."""


def _on_alarm(signum: int, frame: Any) -> None:
    """Stop a run that went over its time limit."""
    raise _TimedOut


def run_one(stage: str, setting: Setting, benchmark: Benchmark) -> dict[str, Any]:
    """
    Find the best schedule for one input at one setting and audit it; then continue it for a second period, with the
    first as history, and do the same for the whole of both (a first period that leaves the second no legal schedule
    is recorded as day 2's "no schedule": a failure, since in real use the next schedule couldn't be made)
    :return: the results row
    """
    row: dict[str, Any] = {"stage": stage, "setting": setting.name, "input": benchmark.name, "tier": benchmark.tier,
                           "holdout": benchmark.holdout,
                           **{field.name: getattr(setting, field.name) for field in dataclasses.fields(Setting)
                              if field.name != "name"}}
    schedule_input = read_input(benchmark.path)
    schedule_input = dataclasses.replace(schedule_input, settings=dataclasses.replace(
        schedule_input.settings, scoring=setting.parameters()))
    problem, constants, status, seconds, result = _solve(schedule_input)
    row |= {"status": status, "seconds": seconds}
    if result is None or result.assignment is None or result.penalty is None:
        return row
    row |= {"nodes": result.nodes, "penalty": round(result.penalty.total, 6), "likes": round(result.penalty.likes, 6),
            "workload": round(result.penalty.workload, 6), "rest": round(result.penalty.rest, 6),
            **audit_fields(schedule_input, problem, result.assignment),
            **measure_fields(problem, constants, result.assignment),
            "assignment": " ".join(map(str, result.assignment))}
    second = next_period(schedule_input, result.assignment)
    problem, constants, status, seconds, result = _solve(second)
    row |= {f"{DAY2}status": status, f"{DAY2}seconds": seconds}
    if result is None or result.assignment is None or result.penalty is None:
        return row
    return {**row, f"{DAY2}nodes": result.nodes, f"{DAY2}penalty": round(result.penalty.total, 6),
            **{DAY2 + field: value for field, value in audit_fields(second, problem, result.assignment).items()},
            **{DAY2 + field: value for field, value in measure_fields(problem, constants, result.assignment).items()},
            f"{DAY2}assignment": " ".join(map(str, result.assignment))}


def _solve(schedule_input: ScheduleInput) -> tuple[Problem, ScoringConstants, str, float, SearchResult | None]:
    """
    Find the best schedule of an input within JOB_TIME_LIMIT
    :return: (its Problem, its ScoringConstants, the status: "done", "no schedule" or "timed out", the seconds taken,
    the SearchResult or None if timed out)
    """
    problem = build_problem(schedule_input)
    settings = problem.settings or schedule_input.settings
    constants = build_constants(settings, problem.workers, problem.shifts, problem.slots, problem.scoring_domains)
    started = time.perf_counter()
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, JOB_TIME_LIMIT)
    try:
        result = find_best_schedule(problem, constants)
    except _TimedOut:
        return problem, constants, "timed out", round(time.perf_counter() - started, 2), None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    status = "done" if result.assignment is not None else "no schedule"
    return problem, constants, status, round(time.perf_counter() - started, 2), result


def next_period(schedule_input: ScheduleInput, assignment: tuple[int, ...]) -> ScheduleInput:
    """
    The input continued for a second period of the same length, right after the first, with the first's schedule as
    its history (ADR 0031): the same workers and posts, each worker's unavailability repeated a period later
    :param schedule_input: ScheduleInput of the first period
    :param assignment: its schedule, a worker index per slot
    :return: ScheduleInput of the second period
    """
    length = schedule_input.settings.period.duration

    def later(time: DateTimeRange) -> DateTimeRange:
        return DateTimeRange(time.start + length, time.end + length)
    workers = tuple(dataclasses.replace(worker, unavailable=tuple(later(away) for away in worker.unavailable))
                    for worker in schedule_input.workers)
    settings = dataclasses.replace(schedule_input.settings, period=later(schedule_input.settings.period))
    return dataclasses.replace(schedule_input, settings=settings, workers=workers,
                               history=(PreviousSchedule("first period", schedule_input, tuple(assignment)),))


def measure_fields(problem: Problem, constants: ScoringConstants, assignment: tuple[int, ...]) -> dict[str, Any]:
    """
    Measures of a schedule that don't come from the audit, over the whole schedule (its history included): each rest
    in available time (ADR 0038), how many are at or below the minimum rest, their median, and the spread of the
    workers' shortest rests; the largest gaps in hours and in shifts between fully available workers (peers); and the
    pairings in shared shifts with someone a worker likes or dislikes (each worker's view counted)
    :param problem: the schedule's Problem (with a history, the whole schedule's, its workers' unavailability too)
    :param constants: its ScoringConstants, for each worker's availability and the minimum rest
    :param assignment: a worker index per slot
    :return: the measure fields of a results row
    """
    times: list[list[DateTimeRange]] = [[] for _ in problem.workers]
    for slot, worker in zip(problem.slots, assignment):
        times[worker].append(slot.time)
    rests, shortest = [], []
    for worker, mine in zip(problem.workers, times):
        mine.sort()
        own = [hours(later.start - earlier.end) - (unavailable_before(worker.unavailable, later.start)
                                                   - unavailable_before(worker.unavailable, earlier.end))
               for earlier, later in zip(mine, mine[1:])]
        rests += own
        if own:
            shortest.append(min(own))
    most = max(worker.availability for worker in constants.workers)
    peers = [index for index, worker in enumerate(constants.workers)
             if worker.availability >= most - EQUAL_AVAILABILITY_TOLERANCE]
    worked = [sum(hours(time.duration) for time in times[index]) for index in peers]
    counts = [len(times[index]) for index in peers]
    liked = disliked = 0
    for shift in problem.shifts:
        together = [problem.workers[assignment[slot.index]] for slot in shift.slots]
        for worker in together:
            liked += sum(1 for partner in together if partner is not worker and partner.name in worker.likes)
            disliked += sum(1 for partner in together if partner is not worker and partner.name in worker.dislikes)
    return {"rests": len(rests),
            "rests_at_minimum": sum(1 for rest in rests if rest <= constants.min_rest + AT_MINIMUM_TOLERANCE),
            "rest_median": round(statistics.median(rests), 4) if rests else "",
            "shortest_rest_spread": round(max(shortest) - min(shortest), 4) if shortest else 0,
            "peer_hours_gap": round(max(worked) - min(worked), 4), "peer_shifts_gap": max(counts) - min(counts),
            "liked_pairings": liked, "disliked_pairings": disliked}


def audit_fields(schedule_input: ScheduleInput, problem: Problem, assignment: tuple[int, ...]) -> dict[str, Any]:
    """
    Audit a schedule
    :param schedule_input: ScheduleInput
    :param problem: its Problem, for the shifts and slots (with a history, the whole schedule's)
    :param assignment: a worker index per slot (with a history, of the whole schedule)
    :return: the audit's fields of a results row
    """
    if schedule_input.history:  # the whole schedule, the history included (ADR 0031)
        context, assignment = with_history(schedule_input, problem.new_shifts, assignment)
    else:
        context = build_context(schedule_input, problem.shifts, problem.slots)
    audit = evaluate(context, assignment)
    summary = summarize(audit, find_fixes(context, assignment, audit))
    return {"complaints": summary.complaints, "easy_fixes": summary.easy_fixes,
            "easy_fix_severity": round(summary.easy_fix_severity, 4),
            "no_fix_severity": round(summary.no_fix_severity, 4), "aggrieved": summary.aggrieved,
            "concentration": round(summary.concentration, 4), "separate_complaints": summary.separate_complaints,
            "separate_severity": round(summary.separate_severity, 4)}


def reaudit_row(row: dict[str, str]) -> dict[str, str]:
    """A results row with its audit fields redone from its stored schedule; rows without one are kept as they are."""
    if row["status"] != "done":
        return row
    schedule_input = read_input(Benchmark(row["input"], row["tier"], row["holdout"] == "True").path)
    schedule_input = dataclasses.replace(schedule_input, settings=dataclasses.replace(
        schedule_input.settings, scoring=_row_parameters(row)))
    assignment = tuple(int(worker) for worker in row["assignment"].split())
    row = {**row, **audit_fields(schedule_input, build_problem(schedule_input), assignment)}
    if row.get(f"{DAY2}status") != "done":
        return row
    second = next_period(schedule_input, assignment)
    whole = tuple(int(worker) for worker in row[f"{DAY2}assignment"].split())
    redone = audit_fields(second, build_problem(second), whole)
    return {**row, **{DAY2 + field: value for field, value in redone.items()}}


def _row_parameters(row: dict[str, str]) -> ScoringParameters:
    """The scoring parameters a results row was run with."""
    return ScoringParameters(float(row["likes_weight"]), float(row["workload_weight"]), float(row["rest_weight"]),
                             int(row["workload_power"]), float(row["neutral_partner"]), float(row["shift_share"]))


def _run_job(job: tuple[str, Setting, Benchmark]) -> dict[str, Any]:
    """run_one, for the pool."""
    return run_one(*job)


# --- running a stage, and its progress ---

def results_path(stage: str) -> pathlib.Path:
    """The results file of a stage."""
    return RESULTS / f"{stage}.csv"


def status_path(stage: str) -> pathlib.Path:
    """The status file of a stage, rewritten as runs finish."""
    return RESULTS / f"{stage}.status.json"


def read_results(stage: str) -> list[dict[str, str]]:
    """The rows written so far for a stage."""
    path = results_path(stage)
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def run_stage(stage: str, jobs: int, planned: list[tuple[Setting, Benchmark]] | None = None) -> None:
    """
    Run every run of a stage not yet in its results file, in parallel, appending each result as it finishes and
    keeping the status file up to date
    :param stage: str, the stage's name
    :param jobs: int, parallel runs
    :param planned: the stage's runs; by default, those of a fixed stage (stage_jobs)
    """
    RESULTS.mkdir(exist_ok=True)
    if results_path(stage).exists():
        with open(results_path(stage), encoding="utf-8", newline="") as file:
            if tuple(csv.DictReader(file).fieldnames or ()) != RESULT_FIELDS:
                raise ValueError(f"{stage}'s results have older columns; re-audit them first (tune.py reaudit)")
    done = {(row["setting"], row["input"]) for row in read_results(stage)}
    planned = stage_jobs(stage) if planned is None else planned
    todo = [(stage, setting, benchmark) for setting, benchmark in planned if (setting.name, benchmark.name) not in done]
    path = results_path(stage)
    new_file = not path.exists()
    started = time.time()
    status = {"stage": stage, "total": len(planned), "done_before": len(planned) - len(todo), "done": 0,
              "timed_out": 0, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "jobs": jobs, "finished": False}
    _write_status(stage, status, started)
    with open(path, "a", encoding="utf-8", newline="") as file, multiprocessing.Pool(jobs) as pool:
        writer = csv.DictWriter(file, RESULT_FIELDS)
        if new_file:
            writer.writeheader()
        for row in pool.imap_unordered(_run_job, todo):
            writer.writerow(row)
            file.flush()
            status["done"] += 1
            status["timed_out"] += row["status"] == "timed out"
            status["last"] = f"{row['setting']} on {row['input']}: {row['status']}, {row['seconds']} s"
            _write_status(stage, status, started)
    status["finished"] = True
    _write_status(stage, status, started)


def reaudit_stage(stage: str, jobs: int) -> None:
    """
    Re-audit a finished stage's stored schedules in place (after the audit changed), keeping the old file as .bak
    :raise ValueError: if the stage has no results, or is still running
    """
    rows = read_results(stage)
    if not rows:
        raise ValueError(f"{stage} has no results")
    path = status_path(stage)
    if path.exists() and not json.loads(path.read_text(encoding="utf-8")).get("finished"):
        raise ValueError(f"{stage} is still running (or was stopped); finish it first")
    with multiprocessing.Pool(jobs) as pool:
        reaudited = pool.map(reaudit_row, rows)
    shutil.copyfile(results_path(stage), results_path(stage).with_suffix(".csv.bak"))
    temporary = results_path(stage).with_suffix(".csv.new")
    with open(temporary, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(reaudited)
    os.replace(temporary, results_path(stage))


def _write_status(stage: str, status: dict[str, Any], started: float) -> None:
    """Write the status file, with the time elapsed and an estimate of the time left."""
    elapsed = time.time() - started
    remaining = status["total"] - status["done_before"] - status["done"]
    status["elapsed_s"] = round(elapsed)
    status["eta_s"] = round(elapsed / status["done"] * remaining) if status["done"] else None
    status["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    status_path(stage).write_text(json.dumps(status, indent=1), encoding="utf-8")


# --- reports ---

def setting_summaries(rows: list[dict[str, str]], include_holdout: bool = False) -> list[dict[str, Any]]:
    """
    Each setting's results over the inputs it finished, ranked by the tuning priorities: severity with an easy fix,
    then concentration, then total severity (all means over the inputs; lower is better). The severity of the
    complaints the audit counts apart (liked partners) is shown, but not ranked on.
    """
    by_setting: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row["status"] == "done" and (include_holdout or row["holdout"] != "True"):
            by_setting.setdefault(row["setting"], []).append(row)
    summaries = []
    for setting, done in by_setting.items():
        def mean(field: str) -> float:
            return statistics.fmean(float(row[field]) for row in done)
        summaries.append({"setting": setting, "inputs": len(done), "easy_fix_severity": mean("easy_fix_severity"),
                          "concentration": mean("concentration"),
                          "total_severity": mean("easy_fix_severity") + mean("no_fix_severity"),
                          "complaints": mean("complaints"), "separate_severity": mean("separate_severity"),
                          "seconds": mean("seconds")})
    return sorted(summaries, key=lambda s: (round(s["easy_fix_severity"], 6), round(s["concentration"], 6),
                                            s["total_severity"]))


def measure_summaries(rows: list[dict[str, str]], include_holdout: bool = False) -> dict[str, dict[str, Any]]:
    """
    Each setting's measures that don't come from the audit, alone and over both periods (day 2), and day 2's audit
    measures: shares and means over the inputs it finished, the largest shift gap between peers (the user tolerates a
    gap of one shift where it can't be helped; two is an outrage), and how many first periods left the second no legal
    schedule
    :return: by setting name
    """
    by_setting: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row["status"] == "done" and (include_holdout or row["holdout"] != "True"):
            by_setting.setdefault(row["setting"], []).append(row)
    summaries = {}
    for setting, done in by_setting.items():
        second = [row for row in done if row.get(f"{DAY2}status") == "done"]
        summary: dict[str, Any] = {"inputs": len(done), "day2_inputs": len(second),
                                   "day2_no_schedule": sum(1 for row in done
                                                           if row.get(f"{DAY2}status") == "no schedule"),
                                   "day2_timed_out": sum(1 for row in done if row.get(f"{DAY2}status") == "timed out")}
        for prefix, group in (("", done), (DAY2, second)):
            if not group:
                continue
            rests = sum(int(row[f"{prefix}rests"]) for row in group)
            at_minimum = sum(int(row[f"{prefix}rests_at_minimum"]) for row in group)
            summary |= {
                f"{prefix}at_minimum": at_minimum / rests if rests else 0,
                f"{prefix}spread": statistics.fmean(float(row[f"{prefix}shortest_rest_spread"]) for row in group),
                f"{prefix}hours_gap": statistics.fmean(float(row[f"{prefix}peer_hours_gap"]) for row in group),
                f"{prefix}shifts_gap_max": max(int(row[f"{prefix}peer_shifts_gap"]) for row in group),
                f"{prefix}disliked": statistics.fmean(int(row[f"{prefix}disliked_pairings"]) for row in group),
                f"{prefix}liked": statistics.fmean(int(row[f"{prefix}liked_pairings"]) for row in group)}
        if second:
            summary |= {"day2_easy_fix_severity": statistics.fmean(float(row[f"{DAY2}easy_fix_severity"])
                                                                   for row in second),
                        "day2_concentration": statistics.fmean(float(row[f"{DAY2}concentration"]) for row in second)}
        summaries[setting] = summary
    return summaries


def unit_tradeoffs(setting: Setting, path: pathlib.Path = EXAMPLE) -> dict[str, Any]:
    """
    What one event of each kind costs at a setting, weighted, on an input (by default the example, which the scoring
    docs use), for an average worker and an average shift; and whether the user's rules hold (2026-11-14): an
    avoidable two-shift gap outweighs OUTRAGE_PAIRINGS likes or dislikes, and one worker resting at the minimum
    twice; a like or dislike can't make up for a worker's second short rest; and a like is worth one short rest,
    within LIKE_PER_SHORT_REST_FACTOR either way
    :param setting: Setting
    :param path: pathlib.Path of the input
    :return: the weighted costs of a like, a dislike (each instead of a neutral partner), a first and a second short
    rest (one average shift's length of rest less, each), one worker resting at the minimum twice (between average
    shifts), one extra shift (taken on by everyone else) and an outrage (one shift moved between two equal workers, a
    gap of two); three ratios; and the four rules' checks
    """
    schedule_input = read_input(path)
    schedule_input = dataclasses.replace(schedule_input, settings=dataclasses.replace(
        schedule_input.settings, scoring=setting.parameters()))
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    parameters = constants.parameters
    available = [worker.availability for worker in constants.workers if worker.availability > 0]
    mean_available = statistics.fmean(available)
    load = statistics.fmean(constants.slot_load)
    per_hour = sum(constants.slot_load) / sum(available)  # the load per available hour at fair shares
    fair = per_hour * mean_available                         # an average worker's fair load
    power = parameters.workload_power

    def term(worker_load: float) -> float:
        return mean_available * (worker_load / mean_available) ** power
    extra_shift = (term(fair + load) - term(fair) - power * per_hour ** (power - 1) * load) / constants.workload_unit
    outrage = (term(fair + load) + term(fair - load) - 2 * term(fair)) / constants.workload_unit
    shift_hours = statistics.fmean(constants.slot_hours)

    def short_by(hours_short: float) -> float:  # an average worker (rest_unit / M_w = 1) short by that many hours
        return hours_short ** REST_POWER / constants.rest_scale
    at_minimum = max(0.0, constants.rest_factor * shift_hours - constants.min_rest)  # two average shifts' target
    costs = {"like": parameters.likes_weight * parameters.neutral_partner,
             "dislike": parameters.likes_weight * (1 - parameters.neutral_partner),
             "first_short_rest": parameters.rest_weight * short_by(shift_hours),
             "second_short_rest": parameters.rest_weight * (short_by(2 * shift_hours) - short_by(shift_hours)),
             "twice_at_minimum": parameters.rest_weight * short_by(2 * at_minimum),  # one worker's shortfall, squared
             "extra_shift": parameters.workload_weight * extra_shift,
             "outrage": parameters.workload_weight * outrage}
    pairing = max(costs["like"], costs["dislike"])
    like_per_short_rest = costs["like"] / costs["first_short_rest"]
    return {**costs, "like_per_short_rest": like_per_short_rest,
            "dislike_per_like": costs["dislike"] / costs["like"],
            "outrage_per_twice_at_minimum": (costs["outrage"] / costs["twice_at_minimum"] if costs["twice_at_minimum"]
                                             else math.inf),
            "outrage_outweighs_pairings": costs["outrage"] > OUTRAGE_PAIRINGS * pairing,
            "outrage_outweighs_twice_at_minimum": costs["outrage"] > costs["twice_at_minimum"],
            "second_short_rest_outweighs_pairing": costs["second_short_rest"] > pairing,
            "like_about_one_short_rest": 1 / LIKE_PER_SHORT_REST_FACTOR <= like_per_short_rest
                                         <= LIKE_PER_SHORT_REST_FACTOR}


def _row_setting(row: dict[str, str]) -> Setting:
    """The setting a results row was run with."""
    return Setting(row["setting"], float(row["likes_weight"]), float(row["workload_weight"]), float(row["rest_weight"]),
                   int(row["workload_power"]), float(row["neutral_partner"]), float(row["shift_share"]))


def stages() -> list[str]:
    """Every stage: the fixed ones, then the rounds started so far, by name."""
    rounds = {path.name.removesuffix(".status.json") for path in RESULTS.glob("*.status.json")} - set(FIXED_STAGES)
    return [*FIXED_STAGES, *sorted(rounds)]


def run_round(name: str, settings: list[str], group: str, jobs: int) -> None:
    """
    Run a tuning round as its own stage, resumable like the others; running it again with more settings adds them
    :param name: str, the round's name
    :param settings: list of str, each a setting as parse_setting reads it
    :param group: str, the input group
    :param jobs: int, parallel runs
    :raise ValueError: on a bad name, setting or group
    """
    if name in FIXED_STAGES or not ROUND_NAME.fullmatch(name):
        raise ValueError(f"a round's name must be letters, digits, - or _, and not {' or '.join(FIXED_STAGES)}")
    run_stage(name, jobs, round_jobs([parse_setting(text) for text in settings], group))


def describe_status(stage: str) -> Iterator[str]:
    """Lines describing a stage's progress."""
    path = status_path(stage)
    if not path.exists():
        yield f"{stage}: not started"
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    finished = status["done_before"] + status["done"]
    state = "finished" if status["finished"] else "running"
    eta = "" if status["finished"] or status["eta_s"] is None else f", about {status['eta_s'] / 60:.0f} min left"
    yield (f"{stage}: {state}, {finished} of {status['total']} runs ({100 * finished / status['total']:.0f}%), "
           f"{status['timed_out']} timed out, {status['elapsed_s'] / 60:.1f} min elapsed{eta}; "
           f"updated {status['updated']}")
    if "last" in status:
        yield f"  last: {status['last']}"


def main(argv: list[str] | None = None) -> int:
    """Run the tuning tool from the command line."""
    parser = argparse.ArgumentParser(prog="tune", description="Tune the scoring parameters against the audit.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a stage")
    run.add_argument("stage", choices=["baseline", "sensitivity"])
    run.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help=f"parallel runs (default {DEFAULT_JOBS})")
    commands.add_parser("status", help="progress of every stage")
    report = commands.add_parser("report", help="each setting's results, best first")
    report.add_argument("stage", help="a fixed stage or a round's name")
    report.add_argument("--holdout", action="store_true", help="include the held-back inputs")
    reaudit = commands.add_parser("reaudit", help="re-audit a finished stage's schedules, after the audit changed")
    reaudit.add_argument("stage", help="a fixed stage or a round's name")
    reaudit.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help=f"parallel audits (default {DEFAULT_JOBS})")
    tuning_round = commands.add_parser("round", help="run a tuning round: the settings given, on a group of inputs")
    tuning_round.add_argument("name", help="the round's name, also its results file's")
    tuning_round.add_argument("--setting", action="append", required=True, metavar="PARAM=VALUE,...",
                              help="a setting to run (repeatable); parameters not given keep their defaults")
    tuning_round.add_argument("--inputs", choices=INPUT_GROUPS, default="tuning",
                              help="the inputs to run on (default: tuning)")
    tuning_round.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help=f"parallel runs (default {DEFAULT_JOBS})")
    arguments = parser.parse_args(argv)
    if arguments.command == "run":
        try:
            run_stage(arguments.stage, arguments.jobs)
        except ValueError as exc:
            print(f"tune: {exc}", file=sys.stderr)
            return 1
    elif arguments.command == "round":
        try:
            run_round(arguments.name, arguments.setting, arguments.inputs, arguments.jobs)
        except ValueError as exc:
            print(f"tune: {exc}", file=sys.stderr)
            return 1
    elif arguments.command == "reaudit":
        try:
            reaudit_stage(arguments.stage, arguments.jobs)
        except ValueError as exc:
            print(f"tune: {exc}", file=sys.stderr)
            return 1
    elif arguments.command == "status":
        for stage in stages():
            print("\n".join(describe_status(stage)))
    else:
        if not read_results(arguments.stage):
            print(f"tune: {arguments.stage} has no results", file=sys.stderr)
            return 1
        print_report(read_results(arguments.stage), arguments.holdout)
    return 0


def print_report(rows: list[dict[str, str]], include_holdout: bool) -> None:
    """Print a stage's report: the audit's measures, the others alone and over two periods, and the trade-offs."""
    summaries = setting_summaries(rows, include_holdout)
    print("The audit, first period alone (ranked by the tuning priorities):")
    print(f"{'setting':<34} {'inputs':>6} {'easy-fix sev.':>13} {'concentration':>13} {'total sev.':>10} "
          f"{'liked-p. sev.':>13} {'seconds':>8}")
    for summary in summaries:
        print(f"{summary['setting']:<34} {summary['inputs']:>6} {summary['easy_fix_severity']:>13.2f} "
              f"{summary['concentration']:>13.2f} {summary['total_severity']:>10.2f} "
              f"{summary['separate_severity']:>13.2f} {summary['seconds']:>8.1f}")
    measures = measure_summaries(rows, include_holdout)
    for prefix, title in (("", "first period alone"), (DAY2, "both periods together (day 2)")):
        print(f"\nOther measures, {title}: rests at the minimum, shortest-rest spread, peer hours gap, largest peer "
              f"shift gap, liked and disliked pairings per input")
        for summary in summaries:
            m = measures[summary["setting"]]
            if f"{prefix}at_minimum" not in m:
                print(f"{summary['setting']:<34} no second period finished")
                continue
            extra = (f"  day 2: {m['day2_inputs']} done, {m['day2_no_schedule']} with no legal schedule, "
                     f"{m['day2_timed_out']} timed out; easy-fix sev. {m['day2_easy_fix_severity']:.2f}, "
                     f"concentration {m['day2_concentration']:.2f}") if prefix else ""
            print(f"{summary['setting']:<34} {m[f'{prefix}at_minimum']:>6.0%} {m[f'{prefix}spread']:>6.1f} "
                  f"{m[f'{prefix}hours_gap']:>6.1f} {m[f'{prefix}shifts_gap_max']:>4} {m[f'{prefix}liked']:>6.1f} "
                  f"{m[f'{prefix}disliked']:>6.1f}{extra}")
    print(f"\nUnit trade-offs on the example, weighted: like, dislike, first and second short rest, at the minimum "
          f"twice, extra shift, outrage; like per short rest, dislike per like, outrage per twice at the minimum; "
          f"rules (outrage > {OUTRAGE_PAIRINGS} pairings, outrage > twice at the minimum, second short rest > a "
          f"pairing, a like about one short rest)")
    settings = {row["setting"]: _row_setting(row) for row in rows}
    for summary in summaries:
        t = unit_tradeoffs(settings[summary["setting"]])
        rules = " ".join("ok" if t[check] else "FAIL" for check in RULE_CHECKS)
        print(f"{summary['setting']:<34} {t['like']:.3f} {t['dislike']:.3f} {t['first_short_rest']:.3f} "
              f"{t['second_short_rest']:.3f} {t['twice_at_minimum']:.3f} {t['extra_shift']:.3f} {t['outrage']:.3f}   "
              f"{t['like_per_short_rest']:.2f} {t['dislike_per_like']:.2f} {t['outrage_per_twice_at_minimum']:.2f}   "
              f"{rules}")


if __name__ == "__main__":
    sys.exit(main())
