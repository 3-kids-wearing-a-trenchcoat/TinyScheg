"""
Tune the scoring parameters (docs/explanation/tuning.md): for each benchmark input and each parameter setting, find
the best schedule by branch and bound, then continue it for a second period with the first as history and find the
best of that too; audit both, and record measures that don't come from the audit. Each setting's unit trade-offs are
checked against the user's rules too. A development tool.
Usage:
  PYTHONPATH=src python tools/tune.py run STAGE [--jobs N]   run a stage (resumable: finished runs are kept)
  PYTHONPATH=src python tools/tune.py status                 progress and results so far
  PYTHONPATH=src python tools/tune.py report STAGE           each setting's results, kind by kind, with the settings
                                                             that dominate it (no single ranking)
  PYTHONPATH=src python tools/tune.py compare STAGE A B [--cards INPUT]
                                                             two settings side by side, worker by worker, on the
                                                             inputs where their schedules differ; with --cards, both
                                                             full audit reports of one input
  PYTHONPATH=src python tools/tune.py reaudit STAGE          re-audit a finished stage's schedules, after the audit
                                                             changed (no new search; the old file is kept, named by
                                                             the time of the re-audit)
  PYTHONPATH=src python tools/tune.py round NAME --setting PARAM=VALUE,... [--setting ...] [--inputs GROUP]
                                                 [--processes N]
                                                             run a tuning round: the settings given ("defaults" for
                                                             the defaults), on a group of inputs (tuning, holdout,
                                                             confirm or multiday), as stage NAME; with --processes,
                                                             one run at a time, each search in N processes
Stages: baseline (the defaults, on every input), sensitivity (one parameter at a time, on the tuning inputs), and
any number of named rounds.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import itertools
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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from audit import (DEFAULT_MAX_CHANGES, FIX_COUNT_FIELDS, HOURS_KINDS, HOURS_MEASURES, HOURS_UNITS, KIND_MEASURES,
                   KIND_ORDER, LONGER_REST_MEASURE, MISSING_LIKE, REST, AuditContext, WorkerTally, aligned,
                   audit_measures, build_context, plural, report_grievances, report_text, shown, tally_cell,
                   with_history)
from tinyscheg.csp.problem import Problem, build_problem
from tinyscheg.csp.next_period import next_period_input
from tinyscheg.csp.parallel import find_best_schedule_in_parallel
from tinyscheg.csp.search import SearchResult
from tinyscheg.model.schedule_input import (DEFAULT_LIKES_WEIGHT, DEFAULT_NEUTRAL_PARTNER, DEFAULT_REST_WEIGHT,
                                            DEFAULT_SHIFT_SHARE, DEFAULT_WORKLOAD_POWER, DEFAULT_WORKLOAD_WEIGHT,
                                            ScheduleInput, ScoringParameters)
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.constants import ScoringConstants, build_constants, hours, unavailable_before
from tinyscheg.scoring.penalty import REST_POWER
from tinyscheg.timing.datetime_range import DateTimeRange

BENCHMARKS = pathlib.Path(__file__).parent / "benchmarks"
MANIFEST = BENCHMARKS / "manifest.csv"
RESULTS = BENCHMARKS / "results"
JOB_TIME_LIMIT = 600.0   # seconds; a run taking longer is recorded as timed out, so one setting can't stall a stage
ONE_AT_A_TIME_TIME_LIMIT = 7200.0  # seconds; the same, for a search run in parallel processes, one run at a time
DEFAULT_JOBS = max(1, (os.cpu_count() or 2) - 2)  # parallel runs, leaving a little of the machine free
FIXED_STAGES = ("baseline", "sensitivity")        # every other stage is a named round
ROUND_NAME = re.compile(r"[A-Za-z0-9_-]+")        # a round's name is also its results file's name
INPUT_GROUPS = ("tuning", "holdout", "confirm", "multiday")  # the inputs a round can run on (see group_inputs)

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

DOMINANCE_EPSILON = 1e-9  # sums of a measure closer than this are equal (hours short are added as floats)
MEASURE_HEADINGS = {"harmless": "with a harmless fix", "most": "most aggrieved", "events": "events",
                    "hours_harmless": "{unit}, harmless fix", "hours_most": "{unit}, most aggrieved",
                    "hours": "{unit}", LONGER_REST_MEASURE: "could be longer"}  # the report's column headings of
# the audit's measures, {unit} from HOURS_UNITS
COLUMN_GAP = 2  # spaces between a table's columns, as audit.aligned leaves them


def kind_field(kind: str, measure: str) -> str:
    """The results column of one kind's measure, e.g. 'disliked_partner_most'."""
    return f"{kind.replace(' ', '_')}_{measure}"


def kind_measure_names(kind: str) -> tuple[str, ...]:
    """
    The measures recorded for one kind: KIND_MEASURES, for load and rest HOURS_MEASURES too, and for rest how many
    workers' shortest rests could have been longer (LONGER_REST_MEASURE, ADR 0055)
    """
    return KIND_MEASURES + (HOURS_MEASURES if kind in HOURS_KINDS else ()) + ((LONGER_REST_MEASURE,) if kind == REST
                                                                              else ())


def measure_heading(kind: str, measure: str) -> str:
    """A measure's column heading in the report, e.g. 'h more, most aggrieved' for load."""
    return MEASURE_HEADINGS[measure].format(unit=HOURS_UNITS.get(kind, ""))


# the audit's measures, per kind (docs/explanation/tuning.md#reading-the-audit): the events with a harmless fix, the
# most aggrieved worker's events and all events, and for load and rest the same in hours (extra hours, hours short);
# K, how far the fix search reached; and each worker's row of the closing table, as JSON, for tune.py compare
KIND_FIELDS = tuple(kind_field(kind, measure) for kind in KIND_ORDER for measure in kind_measure_names(kind))
AUDIT_FIELDS = ("max_changes", *KIND_FIELDS, "by_worker")
# measures that don't come from the audit (rests in available time, ADR 0038; peers are the fully available workers)
MEASURE_FIELDS = ("rests", "rests_at_minimum", "rest_median", "shortest_rest_spread", "peer_hours_gap",
                  "peer_shifts_gap", "liked_pairings", "disliked_pairings")
DAY2 = "day2_"  # the prefix of the second period's fields, measured over both periods together
FIRST_PERIOD = "first period"  # the second period's history entry's source
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
    tier), "confirm" (the confirm tier) or "multiday" (the multiday tier, held-back inputs included)
    :return: list of Benchmark
    """
    if group == "tuning":
        return [benchmark for benchmark in benchmarks() if benchmark.tier == "sweep" and not benchmark.holdout]
    if group == "holdout":
        return [benchmark for benchmark in benchmarks() if benchmark.holdout]
    if group == "confirm":
        return [benchmark for benchmark in benchmarks() if benchmark.tier == "confirm"]
    if group == "multiday":
        return [benchmark for benchmark in benchmarks() if benchmark.tier == "multiday"]
    raise ValueError(f"unknown input group {group!r}; expected one of {', '.join(INPUT_GROUPS)}")


def parse_setting(text: str) -> Setting:
    """
    A setting from the command line: comma-separated PARAM=VALUE pairs, each PARAM a ScoringParameters field, the
    others at their defaults; named by its pairs in field order, so that the same setting always gets the same name.
    "defaults" is the defaults.
    :param text: str, e.g. "neutral_partner=0.25,shift_share=0.5"
    :return: Setting
    :raise ValueError: on an unknown parameter, a value of the wrong type or out of range, or a parameter given twice
    """
    if text.strip() == DEFAULTS.name:
        return DEFAULTS
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


def run_one(stage: str, setting: Setting, benchmark: Benchmark, processes: int = 1) -> dict[str, Any]:
    """
    Find the best schedule for one input at one setting and audit it; then continue it for a second period, with the
    first as history, and do the same for the whole of both (a first period that leaves the second no legal schedule
    is recorded as day 2's "no schedule": a failure, since in real use the next schedule couldn't be made)
    :param stage: str, the stage's name
    :param setting: Setting
    :param benchmark: Benchmark
    :param processes: int, how many processes each search runs in (1: the sequential search, within JOB_TIME_LIMIT;
    more: within ONE_AT_A_TIME_TIME_LIMIT)
    :return: the results row
    """
    row: dict[str, Any] = {"stage": stage, "setting": setting.name, "input": benchmark.name, "tier": benchmark.tier,
                           "holdout": benchmark.holdout,
                           **{field.name: getattr(setting, field.name) for field in dataclasses.fields(Setting)
                              if field.name != "name"}}
    schedule_input = read_input(benchmark.path)
    schedule_input = dataclasses.replace(schedule_input, settings=dataclasses.replace(
        schedule_input.settings, scoring=setting.parameters()))
    problem, constants, status, seconds, result = _solve(schedule_input, processes)
    row |= {"status": status, "seconds": seconds}
    if result is None or result.assignment is None or result.penalty is None:
        return row
    row |= {"nodes": result.nodes, "penalty": round(result.penalty.total, 6), "likes": round(result.penalty.likes, 6),
            "workload": round(result.penalty.workload, 6), "rest": round(result.penalty.rest, 6),
            **audit_fields(schedule_input, problem, result.assignment),
            **measure_fields(problem, constants, result.assignment),
            "assignment": " ".join(map(str, result.assignment))}
    second = next_period(schedule_input, result.assignment)
    problem, constants, status, seconds, result = _solve(second, processes)
    row |= {f"{DAY2}status": status, f"{DAY2}seconds": seconds}
    if result is None or result.assignment is None or result.penalty is None:
        return row
    return {**row, f"{DAY2}nodes": result.nodes, f"{DAY2}penalty": round(result.penalty.total, 6),
            **{DAY2 + field: value for field, value in audit_fields(second, problem, result.assignment).items()},
            **{DAY2 + field: value for field, value in measure_fields(problem, constants, result.assignment).items()},
            f"{DAY2}assignment": " ".join(map(str, result.assignment))}


def _solve(schedule_input: ScheduleInput,
           processes: int = 1) -> tuple[Problem, ScoringConstants, str, float, SearchResult | None]:
    """
    Find the best schedule of an input within the time limit
    :param schedule_input: ScheduleInput
    :param processes: int, how many processes the search runs in (see run_one)
    :return: (its Problem, its ScoringConstants, the status: "done", "no schedule" or "timed out", the seconds taken,
    the SearchResult or None if timed out)
    """
    problem = build_problem(schedule_input)
    settings = problem.settings or schedule_input.settings
    constants = build_constants(settings, problem.workers, problem.shifts, problem.slots, problem.scoring_domains)
    started = time.perf_counter()
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, JOB_TIME_LIMIT if processes == 1 else ONE_AT_A_TIME_TIME_LIMIT)
    try:
        result = find_best_schedule_in_parallel(problem, constants, processes)
    except _TimedOut:
        return problem, constants, "timed out", round(time.perf_counter() - started, 2), None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    status = "done" if result.assignment is not None else "no schedule"
    return problem, constants, status, round(time.perf_counter() - started, 2), result


def next_period(schedule_input: ScheduleInput, assignment: tuple[int, ...]) -> ScheduleInput:
    """
    The input continued for a second period with the same parameters, with the first's schedule as its history: the
    program's own next period (ADR 0042), the same hours a whole number of days later
    :param schedule_input: ScheduleInput of the first period
    :param assignment: its schedule, a worker index per slot
    :return: ScheduleInput of the second period
    """
    return next_period_input(schedule_input, assignment, FIRST_PERIOD)


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


def audit_context(schedule_input: ScheduleInput, problem: Problem,
                  assignment: tuple[int, ...]) -> tuple[AuditContext, tuple[int, ...]]:
    """
    The audit's context and assignment of a schedule: with a history, the whole schedule, the history included (ADR
    0031)
    :param schedule_input: ScheduleInput
    :param problem: its Problem, for the shifts and slots (with a history, the whole schedule's)
    :param assignment: a worker index per slot (with a history, of the whole schedule)
    :return: (the AuditContext, the assignment it audits)
    """
    if schedule_input.history:
        return with_history(schedule_input, problem.new_shifts, assignment)
    return build_context(schedule_input, problem.shifts, problem.slots), assignment


def audit_fields(schedule_input: ScheduleInput, problem: Problem, assignment: tuple[int, ...]) -> dict[str, Any]:
    """
    Audit a schedule, with the fix search reaching the audit's default K
    :param schedule_input: ScheduleInput
    :param problem: its Problem, for the shifts and slots (with a history, the whole schedule's)
    :param assignment: a worker index per slot (with a history, of the whole schedule)
    :return: the audit's fields of a results row
    """
    context, assignment = audit_context(schedule_input, problem, assignment)
    tallies, measures = audit_measures(context, assignment, DEFAULT_MAX_CHANGES)
    return {"max_changes": DEFAULT_MAX_CHANGES,
            **{kind_field(kind, measure): round(value, 4)
               for kind, values in measures.items() for measure, value in values.items()},
            "by_worker": json.dumps([tally_json(tallied) for tallied in tallies], separators=(",", ":"))}


def tally_json(tallied: WorkerTally) -> dict[str, Any]:
    """
    A worker's row of the closing table, for the results file: their counts per kind, in FIX_COUNT_FIELDS order, and
    their hours per kind of HOURS_KINDS (in all, and with a harmless fix)
    """
    return {"name": tallied.name, **{kind: [tallied.counts[kind][field] for field in FIX_COUNT_FIELDS]
                                     for kind in KIND_ORDER},
            "hours": {kind: round(tallied.hours[kind], 4) for kind in HOURS_KINDS},
            "hours_harmless": {kind: round(tallied.hours_harmless[kind], 4) for kind in HOURS_KINDS},
            "longer_rest": tallied.longer_rest}


def tallies_from_json(text: str) -> list[WorkerTally]:
    """Every worker's row of the closing table, read back from a results row's by_worker field."""
    return [WorkerTally(entry["name"], {kind: dict(zip(FIX_COUNT_FIELDS, entry[kind])) for kind in KIND_ORDER},
                        entry["hours"], entry["hours_harmless"], entry.get("longer_rest", False))
            for entry in json.loads(text)]


def reaudit_row(row: dict[str, str]) -> dict[str, str]:
    """
    A results row with its audit fields redone from its stored schedules, and only the current columns (an older
    audit's are dropped); rows without a schedule keep everything else as it was
    """
    row = {field: row.get(field, "") for field in RESULT_FIELDS}
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


def backup_path(stage: str) -> pathlib.Path:
    """Where a stage's results are kept before a re-audit replaces them: named by the time, so none is overwritten."""
    return RESULTS / f"{stage}.csv.{time.strftime('%Y-%m-%dT%H%M%S')}.bak"


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


def run_stage(stage: str, jobs: int, planned: list[tuple[Setting, Benchmark]] | None = None,
              processes: int = 1) -> None:
    """
    Run every run of a stage not yet in its results file, in parallel, appending each result as it finishes and
    keeping the status file up to date
    :param stage: str, the stage's name
    :param jobs: int, parallel runs (with processes 1)
    :param planned: the stage's runs; by default, those of a fixed stage (stage_jobs)
    :param processes: int, 1 to run jobs runs at once, each search in one process; more to run one at a time, each
    search in that many processes
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
              "timed_out": 0, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "jobs": jobs, "processes": processes,
              "finished": False}
    _write_status(stage, status, started)
    with open(path, "a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, RESULT_FIELDS)
        if new_file:
            writer.writeheader()
        for row in _finished_runs(todo, jobs, processes):
            writer.writerow(row)
            file.flush()
            status["done"] += 1
            # searches timed out, day 2's counted too
            status["timed_out"] += (row["status"] == "timed out") + (row.get(f"{DAY2}status") == "timed out")
            status["last"] = f"{row['setting']} on {row['input']}: {row['status']}, {row['seconds']} s"
            _write_status(stage, status, started)
    status["finished"] = True
    _write_status(stage, status, started)


def _finished_runs(todo: Sequence[tuple[str, Setting, Benchmark]], jobs: int,
                   processes: int) -> Iterator[dict[str, Any]]:
    """
    The results rows of a stage's runs, as they finish
    :param todo: the runs, each (stage, setting, benchmark)
    :param jobs: int, parallel runs (with processes 1)
    :param processes: int, 1 for runs in a pool of jobs processes; more for one run at a time in the main process,
    since the pool's processes couldn't start the search's own processes
    :return: an iterator of results rows
    """
    if processes > 1:
        for job in todo:
            yield run_one(*job, processes=processes)
        return
    with multiprocessing.Pool(jobs) as pool:
        yield from pool.imap_unordered(_run_job, todo)


def reaudit_stage(stage: str, jobs: int) -> None:
    """
    Re-audit a finished stage's stored schedules in place (after the audit changed), keeping the old file (backup_path)
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
    shutil.copyfile(results_path(stage), backup_path(stage))
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

def _done_by_setting(rows: list[dict[str, str]], include_holdout: bool,
                     prefix: str = "") -> dict[str, list[dict[str, str]]]:
    """
    The rows of each setting whose search finished (with prefix DAY2, whose second period did), held-back inputs left
    out unless asked for
    :return: by setting name, in the order the settings first appear
    """
    by_setting: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.get(f"{prefix}status") == "done" and (include_holdout or row["holdout"] != "True"):
            by_setting.setdefault(row["setting"], []).append(row)
    return by_setting


def kind_summaries(rows: list[dict[str, str]], include_holdout: bool = False,
                   prefix: str = "") -> list[dict[str, Any]]:
    """
    Each setting's audit measures, kind by kind (KIND_FIELDS), as means over the inputs it finished; the K values its
    audits used; its mean liked pairings, a boon read beside missing likes; and its mean search time. In the stage's
    order: there's no ranking (docs/explanation/tuning.md#reading-the-audit).
    :param rows: a stage's results
    :param include_holdout: True to include the held-back inputs
    :param prefix: "" for the first period alone, DAY2 for both periods together
    :return: a summary per setting
    """
    summaries = []
    for setting, done in _done_by_setting(rows, include_holdout, prefix).items():
        summaries.append({"setting": setting, "inputs": len(done),
                          "k": sorted({int(row[f"{prefix}max_changes"]) for row in done}),
                          **{field: statistics.fmean(float(row[prefix + field]) for row in done)
                             for field in KIND_FIELDS},
                          "liked_pairings": statistics.fmean(int(row[f"{prefix}liked_pairings"]) for row in done),
                          "seconds": statistics.fmean(float(row[f"{prefix}seconds"]) for row in done)})
    return summaries


def dominates(better: Sequence[dict[str, str]], worse: Sequence[dict[str, str]], prefix: str = "") -> bool:
    """
    True if one setting's results dominate another's, on the same inputs: no worse in any of the audit's measures
    (KIND_FIELDS, lower is better) and better in at least one. A comparison, not a weighing: no measure is traded
    against another.
    :param better: the first setting's rows, one per input
    :param worse: the other's, on the same inputs
    :param prefix: "" for the first period alone, DAY2 for both periods together
    """
    strictly = False
    for field in KIND_FIELDS:
        first = math.fsum(float(row[prefix + field]) for row in better)
        second = math.fsum(float(row[prefix + field]) for row in worse)
        if first > second + DOMINANCE_EPSILON:
            return False
        strictly = strictly or first < second - DOMINANCE_EPSILON
    return strictly


def dominated_by(rows: list[dict[str, str]], include_holdout: bool = False, prefix: str = "") -> dict[str, list[str]]:
    """
    For each setting, the settings that dominate it, each pair compared on the inputs both finished. Results audited
    with different K are never compared: a setting audited with more than one K is compared with none.
    :param rows: a stage's results
    :param include_holdout: True to include the held-back inputs
    :param prefix: "" for the first period alone, DAY2 for both periods together
    :return: by setting name, in the stage's order, the names of the settings dominating it, in the same order
    """
    by_setting = _done_by_setting(rows, include_holdout, prefix)
    by_input = {setting: {row["input"]: row for row in done} for setting, done in by_setting.items()}
    k_values = {setting: {row[f"{prefix}max_changes"] for row in done} for setting, done in by_setting.items()}
    result: dict[str, list[str]] = {setting: [] for setting in by_setting}
    for setting, other in itertools.permutations(by_setting, 2):
        if len(k_values[setting]) != 1 or k_values[setting] != k_values[other]:
            continue
        common = [name for name in by_input[setting] if name in by_input[other]]
        if common and dominates([by_input[other][name] for name in common],
                                [by_input[setting][name] for name in common], prefix):
            result[setting].append(other)
    return result


def measure_summaries(rows: list[dict[str, str]], include_holdout: bool = False) -> dict[str, dict[str, Any]]:
    """
    Each setting's measures that don't come from the audit, alone and over both periods (day 2): shares and means over
    the inputs it finished, the largest shift gap between peers (the user tolerates a gap of one shift where it can't
    be helped; two is an outrage), and how many first periods left the second no legal schedule
    :return: by setting name
    """
    summaries = {}
    for setting, done in _done_by_setting(rows, include_holdout).items():
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


def run_round(name: str, settings: list[str], group: str, jobs: int, processes: int = 1) -> None:
    """
    Run a tuning round as its own stage, resumable like the others; running it again with more settings adds them
    :param name: str, the round's name
    :param settings: list of str, each a setting as parse_setting reads it
    :param group: str, the input group
    :param jobs: int, parallel runs
    :param processes: int, see run_stage
    :raise ValueError: on a bad name, setting or group
    """
    if name in FIXED_STAGES or not ROUND_NAME.fullmatch(name):
        raise ValueError(f"a round's name must be letters, digits, - or _, and not {' or '.join(FIXED_STAGES)}")
    run_stage(name, jobs, round_jobs([parse_setting(text) for text in settings], group), processes)


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


# --- comparing two settings, worker by worker ---

def _first_period_rows(rows: list[dict[str, str]], first: str, second: str,
                       include_holdout: bool) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """
    Two settings' finished rows, by input, in the stage's order
    :raise ValueError: if either has no finished run, or their rows were audited with different K (only results with
    the same K are compared)
    """
    found = []
    for setting in (first, second):
        by_input = {row["input"]: row for row in _done_by_setting(rows, include_holdout).get(setting, [])}
        if not by_input:
            raise ValueError(f"{setting!r} has no finished runs in this stage")
        found.append(by_input)
    k_values = sorted({row["max_changes"] for by_input in found for row in by_input.values()})
    if len(k_values) > 1:
        raise ValueError(f"{first!r} and {second!r} were audited with different K ({', '.join(k_values)}); re-audit "
                         f"the stage first (tune.py reaudit)")
    return found[0], found[1]


def compare_cell(tallied: WorkerTally, kind: str, searched: bool) -> str:
    """A worker's cell of one kind, as in the audit's closing table; for load and rest, with the hours too."""
    cell = tally_cell(tallied.counts[kind], searched)
    hours = tallied.hours.get(kind, 0.0)
    return f"{cell} {shown(hours)} {HOURS_UNITS[kind]}" if hours else cell


def compare_input(name: str, first: str, second: str, first_row: dict[str, str],
                  second_row: dict[str, str]) -> list[str]:
    """
    One input's part of a comparison: both settings' closing tables side by side, every worker in input order, then
    each worker's cell that differs, before and after, as a reading aid (the tables are the whole of it)
    :param name: the input's name
    :param first: the first setting's name
    :param second: the second's
    :param first_row: the first setting's results row on the input
    :param second_row: the second's
    :return: the lines
    """
    searched = int(first_row["max_changes"]) > 0
    table = [["", *KIND_ORDER, "|", *KIND_ORDER]]
    differences = []
    for before, after in zip(tallies_from_json(first_row["by_worker"]), tallies_from_json(second_row["by_worker"])):
        cells = [compare_cell(before, kind, searched) for kind in KIND_ORDER]
        others = [compare_cell(after, kind, searched) for kind in KIND_ORDER]
        table.append([before.name, *cells, "|", *others])
        differences += [f"{before.name} {kind}: {old} → {new}"
                        for kind, old, new in zip(KIND_ORDER, cells, others) if old != new]
    widths = [max(len(row[column]) for row in table) for column in range(len(table[0]))]
    names_line = " " * (widths[0] + COLUMN_GAP) + first
    right_half = sum(widths[:len(KIND_ORDER) + 2]) + COLUMN_GAP * (len(KIND_ORDER) + 2)  # where the second half starts
    names_line += " " * max(COLUMN_GAP, right_half - len(names_line)) + second
    if not differences:
        return [name, names_line, *aligned(table),
                "differences: none in the counts (the schedules differ, but every worker's cells are equal)"]
    return [name, names_line, *aligned(table), "differences:", *(f"  {difference}" for difference in differences)]


def compare_settings(rows: list[dict[str, str]], first: str, second: str, include_holdout: bool = False) -> str:
    """
    Two settings of a stage, for reading by hand (docs/explanation/tuning.md#reading-the-audit): on each input where
    their first-period schedules differ, both closing tables side by side and the cells that differ; then the inputs
    where both gave the same schedule (so the same audit), and those only one of them finished
    :param rows: the stage's results
    :param first: a setting's name
    :param second: another's
    :param include_holdout: True to include the held-back inputs
    :return: the comparison, as text
    :raise ValueError: see _first_period_rows
    """
    left, right = _first_period_rows(rows, first, second, include_holdout)
    common = [name for name in left if name in right]
    same = [name for name in common if left[name]["assignment"] == right[name]["assignment"]]
    differing = [name for name in common if name not in same]
    max_changes = int(next(iter(left.values()))["max_changes"])
    reach = f"fixes searched up to {plural(max_changes, 'change')}" if max_changes > 0 else "fix search off"
    lines = [f"{first} | {second}: {len(differing)} of {len(common)} inputs give different first-period schedules; "
             f"{reach}; each cell is a worker's events, as in the audit's closing table "
             f"(with a harmless fix / only transfers / no fix / in the history), and for rest the hours short"]
    for name in differing:
        lines += ["", *compare_input(name, first, second, left[name], right[name])]
    lines += ["", "same schedule under both: " + (", ".join(same) or "none")]
    only = ([f"{name} ({first})" for name in left if name not in right]
            + [f"{name} ({second})" for name in right if name not in left])
    if only:
        lines.append("finished under only one: " + ", ".join(only))
    return "\n".join(lines)


def audit_report(row: dict[str, str]) -> str:
    """The full audit report of a results row's first-period schedule, audited again with the K it was audited with."""
    schedule_input = read_input(Benchmark(row["input"], row["tier"], row["holdout"] == "True").path)
    assignment = tuple(int(worker) for worker in row["assignment"].split())
    context, assignment = audit_context(schedule_input, build_problem(schedule_input), assignment)
    return report_text(context, assignment, report_grievances(context, assignment, int(row["max_changes"])))


def compare_cards(rows: list[dict[str, str]], first: str, second: str, input_name: str) -> str:
    """
    Both settings' full audit reports of one input's first period (its cards, with every event and fix), audited
    again from the stored schedules
    :param rows: the stage's results
    :param first: a setting's name
    :param second: another's
    :param input_name: the input's name (held-back inputs included)
    :return: both reports, as text
    :raise ValueError: if either setting didn't finish the input, or see _first_period_rows
    """
    left, right = _first_period_rows(rows, first, second, include_holdout=True)
    parts = []
    for setting, by_input in ((first, left), (second, right)):
        if input_name not in by_input:
            raise ValueError(f"{setting!r} has no finished run on {input_name!r}")
        parts.append(f"=== {setting}, on {input_name} (first period) ===\n\n{audit_report(by_input[input_name])}")
    return "\n\n".join(parts)


def current_columns(rows: list[dict[str, str]], stage: str) -> None:
    """
    :raise ValueError: if a stage's results were recorded with an older audit's columns
    """
    if rows and not set(AUDIT_FIELDS) <= rows[0].keys():
        raise ValueError(f"{stage}'s results have an older audit's columns; re-audit them first (tune.py reaudit "
                         f"{stage})")


def main(argv: list[str] | None = None) -> int:
    """Run the tuning tool from the command line."""
    parser = argparse.ArgumentParser(prog="tune", description="Tune the scoring parameters against the audit.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a stage")
    run.add_argument("stage", choices=["baseline", "sensitivity"])
    run.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help=f"parallel runs (default {DEFAULT_JOBS})")
    commands.add_parser("status", help="progress of every stage")
    report = commands.add_parser("report", help="each setting's results, kind by kind, with the settings that "
                                                "dominate it")
    report.add_argument("stage", help="a fixed stage or a round's name")
    report.add_argument("--holdout", action="store_true", help="include the held-back inputs")
    compare = commands.add_parser("compare", help="two settings side by side, worker by worker, on the inputs where "
                                                  "their schedules differ")
    compare.add_argument("stage", help="a fixed stage or a round's name")
    compare.add_argument("first", help="a setting's name, as the report shows it")
    compare.add_argument("second", help="another setting's name")
    compare.add_argument("--holdout", action="store_true", help="include the held-back inputs")
    compare.add_argument("--cards", metavar="INPUT",
                         help="print both settings' full audit reports of this input instead")
    reaudit = commands.add_parser("reaudit", help="re-audit a finished stage's schedules, after the audit changed")
    reaudit.add_argument("stage", help="a fixed stage or a round's name")
    reaudit.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help=f"parallel audits (default {DEFAULT_JOBS})")
    tuning_round = commands.add_parser("round", help="run a tuning round: the settings given, on a group of inputs")
    tuning_round.add_argument("name", help="the round's name, also its results file's")
    tuning_round.add_argument("--setting", action="append", required=True, metavar="PARAM=VALUE,...",
                              help="a setting to run (repeatable); parameters not given keep their defaults; "
                                   "\"defaults\" for the defaults")
    tuning_round.add_argument("--inputs", choices=INPUT_GROUPS, default="tuning",
                              help="the inputs to run on (default: tuning)")
    tuning_round.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help=f"parallel runs (default {DEFAULT_JOBS})")
    tuning_round.add_argument("--processes", type=int, default=1,
                              help="run one run at a time, each search in this many processes (for long inputs)")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "run":
            run_stage(arguments.stage, arguments.jobs)
        elif arguments.command == "round":
            if arguments.processes < 1:
                raise ValueError("the number of processes must be at least 1")
            run_round(arguments.name, arguments.setting, arguments.inputs, arguments.jobs, arguments.processes)
        elif arguments.command == "reaudit":
            reaudit_stage(arguments.stage, arguments.jobs)
        elif arguments.command == "status":
            for stage in stages():
                print("\n".join(describe_status(stage)))
        else:
            rows = read_results(arguments.stage)
            if not rows:
                raise ValueError(f"{arguments.stage} has no results")
            current_columns(rows, arguments.stage)
            if arguments.command == "report":
                print_report(rows, arguments.holdout)
            elif arguments.cards:
                print(compare_cards(rows, arguments.first, arguments.second, arguments.cards))
            else:
                print(compare_settings(rows, arguments.first, arguments.second, arguments.holdout))
    except ValueError as exc:
        print(f"tune: {exc}", file=sys.stderr)
        return 1
    return 0


def describe_audit(rows: list[dict[str, str]], include_holdout: bool, prefix: str, title: str) -> list[str]:
    """
    The audit's part of a stage's report: each kind's measures, setting by setting (in the stage's order, no
    ranking), then the settings dominating each; results audited with different K are flagged and never compared
    :param rows: the stage's results
    :param include_holdout: True to include the held-back inputs
    :param prefix: "" for the first period alone, DAY2 for both periods together
    :param title: which of the two, for the headings
    :return: the lines
    """
    lines = [f"The audit, {title}: each kind's measures, means over the inputs each setting finished (lower is "
             f"better; kinds are never added together)"]
    summaries = kind_summaries(rows, include_holdout, prefix)
    if not summaries:
        return lines + ["no run finished"]
    k_values = sorted({k for summary in summaries for k in summary["k"]})
    mixed = len(k_values) > 1
    if mixed:
        lines.append(f"WARNING: audited with different K ({', '.join(map(str, k_values))}), which are never compared: "
                     f"re-audit the stage (tune.py reaudit)")
    else:
        lines.append(f"fixes searched up to {plural(k_values[0], 'change')}" if k_values[0] > 0 else "fix search off")

    def label(summary: dict[str, Any]) -> str:
        return summary["setting"] + (f" [K={','.join(map(str, summary['k']))}]" if mixed else "")
    for kind in KIND_ORDER:
        measures = kind_measure_names(kind)
        liked = kind == MISSING_LIKE  # liked pairings, a boon, read beside missing likes
        table = [["setting", "inputs", *(measure_heading(kind, measure) for measure in measures)]
                 + (["liked pairings"] if liked else [])]
        table += [[label(summary), str(summary["inputs"]),
                   *(f"{summary[kind_field(kind, measure)]:.2f}" for measure in measures)]
                  + ([f"{summary['liked_pairings']:.2f}"] if liked else []) for summary in summaries]
        lines += ["", f"{kind}:", *aligned(table)]
    dominance = dominated_by(rows, include_holdout, prefix)
    lines += ["", f"dominance, {title}: on the inputs both settings finished, every measure of every kind"]
    table = []
    for summary in summaries:
        if len(summary["k"]) > 1:
            verdict = "not compared: audited with more than one K"
        elif dominance[summary["setting"]]:
            verdict = "dominated by " + ", ".join(dominance[summary["setting"]])
        else:
            verdict = "not dominated"
        table.append([label(summary), f"search {summary['seconds']:.1f} s", verdict])
    return lines + aligned(table)


def print_report(rows: list[dict[str, str]], include_holdout: bool) -> None:
    """
    Print a stage's report: the audit's measures kind by kind with dominance, alone and over two periods; the other
    measures, alone and over two periods; and the trade-offs
    """
    for prefix, title in (("", "first period alone"), (DAY2, "both periods together (day 2)")):
        print("\n".join(describe_audit(rows, include_holdout, prefix, title)), end="\n\n")
    order = list(_done_by_setting(rows, include_holdout))
    measures = measure_summaries(rows, include_holdout)
    for prefix, title in (("", "first period alone"), (DAY2, "both periods together (day 2)")):
        print(f"Other measures, {title}: rests at the minimum, shortest-rest spread, peer hours gap, largest peer "
              f"shift gap, liked and disliked pairings per input")
        for setting in order:
            m = measures[setting]
            if f"{prefix}at_minimum" not in m:
                print(f"{setting:<34} no second period finished")
                continue
            extra = (f"  day 2: {m['day2_inputs']} done, {m['day2_no_schedule']} with no legal schedule, "
                     f"{m['day2_timed_out']} timed out") if prefix else ""
            print(f"{setting:<34} {m[f'{prefix}at_minimum']:>6.0%} {m[f'{prefix}spread']:>6.1f} "
                  f"{m[f'{prefix}hours_gap']:>6.1f} {m[f'{prefix}shifts_gap_max']:>4} {m[f'{prefix}liked']:>6.1f} "
                  f"{m[f'{prefix}disliked']:>6.1f}{extra}")
        print()
    print(f"Unit trade-offs on the example, weighted: like, dislike, first and second short rest, at the minimum "
          f"twice, extra shift, outrage; like per short rest, dislike per like, outrage per twice at the minimum; "
          f"rules (outrage > {OUTRAGE_PAIRINGS} pairings, outrage > twice at the minimum, second short rest > a "
          f"pairing, a like about one short rest)")
    settings = {row["setting"]: _row_setting(row) for row in rows}
    for setting in order:
        t = unit_tradeoffs(settings[setting])
        rules = " ".join("ok" if t[check] else "FAIL" for check in RULE_CHECKS)
        print(f"{setting:<34} {t['like']:.3f} {t['dislike']:.3f} {t['first_short_rest']:.3f} "
              f"{t['second_short_rest']:.3f} {t['twice_at_minimum']:.3f} {t['extra_shift']:.3f} {t['outrage']:.3f}   "
              f"{t['like_per_short_rest']:.2f} {t['dislike_per_like']:.2f} {t['outrage_per_twice_at_minimum']:.2f}   "
              f"{rules}")


if __name__ == "__main__":
    sys.exit(main())
