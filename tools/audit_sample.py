"""
Compare the schedule audit with the internal penalty (docs/explanation/schedule-audit.md#sampling): many legal
schedules for one input, made by shuffling the workers' order before the search, each audited and scored, and read
kind by kind (kinds are never added together).
Usage: PYTHONPATH=src python tools/audit_sample.py INPUT [-n COUNT] [--max-changes K]
"""
from __future__ import annotations

import argparse
import dataclasses
import math
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from audit import (DEFAULT_MAX_CHANGES, KIND_ORDER, REST, audit_measures, build_context, non_negative, plural,
                   shown)
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.validation import InputError
from tinyscheg.scoring.constants import build_constants
from tinyscheg.scoring.penalty import Penalty, score

DEFAULT_SAMPLES = 20       # schedules sampled when no count is given
BEST_SHARE = 0.25          # disagreements are looked for among this share of the samples, the best by penalty
DISAGREEMENTS_SHOWN = 3    # how many disagreements are listed per kind, the best by penalty first

EXIT_SUCCESS = 0
EXIT_NO_SCHEDULE = 1
EXIT_USAGE = 2


@dataclass(frozen=True, slots=True)
class Sample:
    """
    One sampled schedule: the seed its worker order was shuffled with, its penalty, and its audit's measures per kind
    (audit.kind_measures)
    """
    seed: int
    assignment: tuple[int, ...]
    penalty: Penalty
    measures: dict[str, dict[str, float]]


def shuffled_schedule(schedule_input: ScheduleInput, seed: int) -> tuple[int, ...] | None:
    """
    The first legal schedule found with the workers in a shuffled order
    :param schedule_input: ScheduleInput
    :param seed: the seed of the shuffle
    :return: a worker index (in the original order) per slot, or None if no legal schedule exists
    """
    workers = list(schedule_input.workers)
    random.Random(seed).shuffle(workers)
    shuffled = dataclasses.replace(schedule_input, workers=tuple(workers))
    assignment = find_first_schedule(build_problem(shuffled)).assignment  # posts are unchanged, so slots are too
    if assignment is None:
        return None
    original_index = {worker.name: index for index, worker in enumerate(schedule_input.workers)}
    return tuple(original_index[workers[worker].name] for worker in assignment)


def take_samples(schedule_input: ScheduleInput, count: int, max_changes: int = DEFAULT_MAX_CHANGES) -> list[Sample]:
    """
    Sample, audit and score schedules
    :param schedule_input: ScheduleInput
    :param count: how many schedules to sample (seeds 0 to count - 1)
    :param max_changes: how far the audit's fix search reaches; 0 turns it off
    :return: the samples, in seed order; empty if no legal schedule exists
    """
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    context = build_context(schedule_input, problem.shifts, problem.slots)
    samples = []
    for seed in range(count):
        assignment = shuffled_schedule(schedule_input, seed)
        if assignment is None:
            return []
        measures = audit_measures(context, assignment, max_changes)[1]
        samples.append(Sample(seed, assignment, score(constants, assignment), measures))
    return samples


def ranks(values: Sequence[float]) -> list[float]:
    """Each value's rank, from 1, with tied values sharing the average of their ranks."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            result[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return result


def spearman(first: Sequence[float], second: Sequence[float]) -> float | None:
    """The Spearman rank correlation of two equally long sequences, or None if either is constant."""
    x, y = ranks(first), ranks(second)
    mean_x, mean_y = math.fsum(x) / len(x), math.fsum(y) / len(y)
    covariance = math.fsum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    spread = math.sqrt(math.fsum((a - mean_x) ** 2 for a in x) * math.fsum((b - mean_y) ** 2 for b in y))
    return covariance / spread if spread else None


def disagreements(samples: Sequence[Sample]) -> dict[str, list[Sample]]:
    """
    For each kind, the samples among the best by penalty (BEST_SHARE of them) that still have events of that kind with
    a harmless fix: a harmless fix in a schedule the penalty favours is a direct sign it missed something
    :return: per kind (KIND_ORDER), up to DISAGREEMENTS_SHOWN samples, the best by penalty first
    """
    best = sorted(samples, key=lambda sample: (sample.penalty.total, sample.seed))
    best = best[:max(1, math.ceil(len(samples) * BEST_SHARE))]
    return {kind: [sample for sample in best if sample.measures[kind]["harmless"] > 0][:DISAGREEMENTS_SHOWN]
            for kind in KIND_ORDER}


def describe_sample(sample: Sample) -> str:
    """One line per sample: its seed and penalty, and each kind's events (with a harmless fix), for rest hours short."""
    kinds = []
    for kind in KIND_ORDER:
        measures = sample.measures[kind]
        hours = f", {shown(measures['hours'])} h short" if kind == REST and measures["hours"] else ""
        kinds.append(f"{kind} {shown(measures['events'])} ({shown(measures['harmless'])}){hours}")
    return f"seed {sample.seed:>3}: penalty {shown(sample.penalty.total):>5}  " + "  ".join(kinds)


def describe_correlation(penalties: Sequence[float], samples: Sequence[Sample], kind: str, measure: str) -> str:
    """The rank correlation of the penalty with one kind's measure, or why there's none."""
    correlation = spearman(penalties, [sample.measures[kind][measure] for sample in samples])
    return "n/a (constant)" if correlation is None else shown(correlation)


def report(samples: Sequence[Sample], max_changes: int = DEFAULT_MAX_CHANGES) -> str:
    """
    The sampling report: every sample by penalty, the rank correlation of the penalty with each kind's events (all,
    and with a harmless fix; for rest in hours short too), and each kind's disagreements
    :param samples: the samples
    :param max_changes: how far the audit's fix search reached
    :return: the report, as text
    """
    by_penalty = sorted(samples, key=lambda sample: (sample.penalty.total, sample.seed))
    reach = f"fixes searched up to {plural(max_changes, 'change')}" if max_changes > 0 else "fix search off"
    lines = [f"each kind's events (with a harmless fix); {reach}"] + [describe_sample(sample) for sample in by_penalty]
    distinct = len({sample.assignment for sample in samples})
    penalties = [sample.penalty.total for sample in samples]
    lines += ["", f"{len(samples)} samples, {distinct} distinct schedules",
              "rank correlation of the penalty with each kind's events (all / with a harmless fix):"]
    for kind in KIND_ORDER:
        line = (f"  {kind}: {describe_correlation(penalties, samples, kind, 'events')} / "
                f"{describe_correlation(penalties, samples, kind, 'harmless')}")
        if kind == REST:
            line += (f"; in hours short: {describe_correlation(penalties, samples, kind, 'hours')} / "
                     f"{describe_correlation(penalties, samples, kind, 'hours_harmless')}")
        lines.append(line)
    lines.append(f"disagreements (the best {shown(BEST_SHARE * 100)}% by penalty, still with a harmless fix), by kind:")
    for kind, found in disagreements(samples).items():
        lines.append(f"  {kind}: " + (", ".join(f"seed {sample.seed}" for sample in found) if found else "none"))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the sampler from the command line
    :param argv: the arguments, without the program name; None means sys.argv[1:]
    :return: the exit code
    """
    parser = argparse.ArgumentParser(prog="audit_sample",
                                     description="Compare the schedule audit with the internal penalty.")
    parser.add_argument("input", help="the YAML input file")
    parser.add_argument("-n", "--count", type=int, default=DEFAULT_SAMPLES,
                        help=f"how many schedules to sample (default {DEFAULT_SAMPLES})")
    parser.add_argument("--max-changes", type=non_negative, default=DEFAULT_MAX_CHANGES, metavar="K",
                        help=f"how many moves and swaps the audit's fix search reaches (default "
                             f"{DEFAULT_MAX_CHANGES}); 0 turns it off")
    arguments = parser.parse_args(argv)
    if arguments.count < 1:
        parser.error("the count must be at least 1")
    try:
        schedule_input = read_input(arguments.input)
    except InputError as exc:
        print(f"audit_sample: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print(f"audit_sample: can't read {arguments.input}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_USAGE
    samples = take_samples(schedule_input, arguments.count, arguments.max_changes)
    if not samples:
        print("audit_sample: no legal schedule exists", file=sys.stderr)
        return EXIT_NO_SCHEDULE
    print(report(samples, arguments.max_changes))
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
