"""
Compare the schedule audit with the internal penalty (docs/explanation/schedule-audit.md#sampling): many legal
schedules for one input, made by shuffling the workers' order before the search, each audited and scored.
Usage: PYTHONPATH=src python tools/audit_sample.py INPUT [-n COUNT]
"""
from __future__ import annotations

import argparse
import dataclasses
import math
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from audit import AuditSummary, build_context, evaluate, find_fixes, shown, summarize
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.validation import InputError
from tinyscheg.scoring.constants import build_constants
from tinyscheg.scoring.penalty import Penalty, score

DEFAULT_SAMPLES = 20       # schedules sampled when no count is given
BEST_SHARE = 0.25          # disagreements are looked for among this share of the samples, the best by penalty
DISAGREEMENTS_SHOWN = 3    # how many disagreements are listed

EXIT_SUCCESS = 0
EXIT_NO_SCHEDULE = 1
EXIT_USAGE = 2


@dataclass(frozen=True, slots=True)
class Sample:
    """One sampled schedule: the seed its worker order was shuffled with, its penalty and its audit summary."""
    seed: int
    assignment: tuple[int, ...]
    penalty: Penalty
    summary: AuditSummary


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


def take_samples(schedule_input: ScheduleInput, count: int) -> list[Sample]:
    """
    Sample, audit and score schedules
    :param schedule_input: ScheduleInput
    :param count: how many schedules to sample (seeds 0 to count - 1)
    :return: the samples, in seed order; empty if no legal schedule exists
    """
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    context = build_context(schedule_input, problem.shifts, problem.slots)
    samples = []
    for seed in range(count):
        assignment = shuffled_schedule(schedule_input, seed)
        if assignment is None:
            return []
        audit = evaluate(context, assignment)
        summary = summarize(audit, find_fixes(context, assignment, audit))
        samples.append(Sample(seed, assignment, score(constants, assignment), summary))
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
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    spread = math.sqrt(sum((a - mean_x) ** 2 for a in x) * sum((b - mean_y) ** 2 for b in y))
    return covariance / spread if spread else None


def disagreements(samples: Sequence[Sample]) -> list[Sample]:
    """Among the best samples by penalty (BEST_SHARE of them), those with the most severity that has an easy fix."""
    best = sorted(samples, key=lambda sample: (sample.penalty.total, sample.seed))
    best = best[:max(1, math.ceil(len(samples) * BEST_SHARE))]
    worst_audits = sorted(best, key=lambda sample: (-sample.summary.easy_fix_severity, sample.seed))
    return [sample for sample in worst_audits[:DISAGREEMENTS_SHOWN] if sample.summary.easy_fix_severity > 0]


def describe_sample(sample: Sample) -> str:
    """One line per sample: its seed, penalty and audit summary."""
    summary = sample.summary
    return (f"seed {sample.seed:>3}: penalty {shown(sample.penalty.total):>5}  severity: easy fix "
            f"{shown(summary.easy_fix_severity):>5}, none found {shown(summary.no_fix_severity):>5}  "
            f"complaints {summary.complaints:>3} ({summary.easy_fixes} with an easy fix)  concentration "
            f"{shown(summary.concentration)}")


def report(samples: Sequence[Sample]) -> str:
    """The sampling report: every sample by penalty, the rank correlation and the disagreements."""
    by_penalty = sorted(samples, key=lambda sample: (sample.penalty.total, sample.seed))
    lines = [describe_sample(sample) for sample in by_penalty]
    distinct = len({sample.assignment for sample in samples})
    penalties = [sample.penalty.total for sample in samples]
    lines += ["", f"{len(samples)} samples, {distinct} distinct schedules"]
    summaries = [sample.summary for sample in samples]
    for name, severities in (("severity with an easy fix", [summary.easy_fix_severity for summary in summaries]),
                             ("total severity", [summary.easy_fix_severity + summary.no_fix_severity
                                                 for summary in summaries])):
        correlation = spearman(penalties, severities)
        lines.append(f"rank correlation of penalty and {name}: "
                     + ("n/a (one of them is constant)" if correlation is None else shown(correlation)))
    found = disagreements(samples)
    lines.append(f"disagreements (best {shown(BEST_SHARE * 100)}% by penalty, most severity with an easy fix): "
                 + (", ".join(f"seed {sample.seed}" for sample in found) if found else "none"))
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
    samples = take_samples(schedule_input, arguments.count)
    if not samples:
        print("audit_sample: no legal schedule exists", file=sys.stderr)
        return EXIT_NO_SCHEDULE
    print(report(samples))
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
