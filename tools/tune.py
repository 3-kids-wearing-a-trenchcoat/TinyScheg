"""
Tune the scoring parameters against the schedule audit (docs/explanation/tuning.md): for each benchmark input and
each parameter setting, find the best schedule by branch and bound and audit it. A development tool.
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

from audit import build_context, evaluate, find_fixes, summarize
from tinyscheg.csp.problem import Problem, build_problem
from tinyscheg.csp.search import find_best_schedule
from tinyscheg.model.schedule_input import (DEFAULT_LIKES_WEIGHT, DEFAULT_NEUTRAL_PARTNER, DEFAULT_REST_WEIGHT,
                                            DEFAULT_SHIFT_SHARE, DEFAULT_WORKLOAD_POWER, DEFAULT_WORKLOAD_WEIGHT,
                                            ScheduleInput, ScoringParameters)
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.constants import build_constants

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

RESULT_FIELDS = ("stage", "setting", "input", "tier", "holdout", "likes_weight", "workload_weight", "rest_weight",
                 "workload_power", "neutral_partner", "shift_share", "status", "seconds", "nodes",
                 "penalty", "likes", "workload", "rest", "complaints", "easy_fixes", "easy_fix_severity",
                 "no_fix_severity", "aggrieved", "concentration", "separate_complaints", "separate_severity",
                 "assignment")


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
    Find the best schedule for one input at one setting, and audit it
    :return: the results row
    """
    row: dict[str, Any] = {"stage": stage, "setting": setting.name, "input": benchmark.name, "tier": benchmark.tier,
                           "holdout": benchmark.holdout,
                           **{field.name: getattr(setting, field.name) for field in dataclasses.fields(Setting)
                              if field.name != "name"}}
    schedule_input = read_input(benchmark.path)
    schedule_input = dataclasses.replace(schedule_input, settings=dataclasses.replace(
        schedule_input.settings, scoring=setting.parameters()))
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    started = time.perf_counter()
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, JOB_TIME_LIMIT)
    try:
        result = find_best_schedule(problem, constants)
    except _TimedOut:
        return {**row, "status": "timed out", "seconds": round(time.perf_counter() - started, 2)}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    seconds = time.perf_counter() - started
    if result.assignment is None or result.penalty is None:
        return {**row, "status": "no schedule", "seconds": round(seconds, 2)}
    return {**row, "status": "done", "seconds": round(seconds, 2), "nodes": result.nodes,
            "penalty": round(result.penalty.total, 6), "likes": round(result.penalty.likes, 6),
            "workload": round(result.penalty.workload, 6), "rest": round(result.penalty.rest, 6),
            **audit_fields(schedule_input, problem, result.assignment),
            "assignment": " ".join(map(str, result.assignment))}


def audit_fields(schedule_input: ScheduleInput, problem: Problem, assignment: tuple[int, ...]) -> dict[str, Any]:
    """
    Audit a schedule
    :param schedule_input: ScheduleInput
    :param problem: its Problem, for the shifts and slots
    :param assignment: a worker index per slot
    :return: the audit's fields of a results row
    """
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
    assignment = tuple(int(worker) for worker in row["assignment"].split())
    return {**row, **audit_fields(schedule_input, build_problem(schedule_input), assignment)}


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
        print(f"{'setting':<34} {'inputs':>6} {'easy-fix sev.':>13} {'concentration':>13} {'total sev.':>10} "
              f"{'liked-p. sev.':>13} {'seconds':>8}")
        for summary in setting_summaries(read_results(arguments.stage), arguments.holdout):
            print(f"{summary['setting']:<34} {summary['inputs']:>6} {summary['easy_fix_severity']:>13.2f} "
                  f"{summary['concentration']:>13.2f} {summary['total_severity']:>10.2f} "
                  f"{summary['separate_severity']:>13.2f} {summary['seconds']:>8.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
