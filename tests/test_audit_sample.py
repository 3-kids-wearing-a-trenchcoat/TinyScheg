"""Tests for tools/audit_sample.py."""
import dataclasses
import pathlib

import pytest

from audit import AuditSummary
from audit_sample import (EXIT_NO_SCHEDULE, EXIT_SUCCESS, Sample, disagreements, main, ranks, shuffled_schedule,
                          spearman, take_samples)
from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.scoring.penalty import Penalty

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"


def test_ties_share_their_average_rank() -> None:
    assert ranks([3.0, 1.0, 3.0, 2.0]) == [3.5, 1.0, 3.5, 2.0]


def test_spearman() -> None:
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1)
    assert spearman([1, 2, 3], [9, 4, 1]) == pytest.approx(-1)
    assert spearman([1, 2, 3], [5, 5, 5]) is None


def test_shuffled_schedules_are_legal_in_the_original_worker_order() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    slots = build_problem(schedule_input).slots
    for seed in range(3):
        assignment = shuffled_schedule(schedule_input, seed)
        assert assignment is not None
        assert hard_constraint_violations(schedule_input, slots, assignment) == []


def test_disagreements_are_the_best_by_penalty_with_the_most_severity_with_an_easy_fix() -> None:
    def sample(seed: int, penalty: float, easy_fix_severity: float) -> Sample:
        summary = AuditSummary(0, 0, easy_fix_severity, 0.0, 0, 0.0, ())
        return Sample(seed, (seed,), Penalty(penalty, 0, 0, 0), summary)
    samples = [sample(0, 1.0, 0.0), sample(1, 2.0, 5.0), sample(2, 3.0, 9.0), sample(3, 4.0, 9.0)]
    # the best quarter of four is one sample, seed 0, with nothing that has an easy fix
    assert disagreements(samples) == []
    samples[0] = dataclasses.replace(samples[0], summary=AuditSummary(0, 0, 2.0, 0.0, 0, 0.0, ()))
    assert [found.seed for found in disagreements(samples)] == [0]


def test_command_line(capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path) -> None:
    assert len(take_samples(read_input(EXAMPLE_INPUT), 2)) == 2
    assert main([str(EXAMPLE_INPUT), "-n", "2"]) == EXIT_SUCCESS
    assert "2 samples" in capsys.readouterr().out
    infeasible = tmp_path / "input.yml"
    infeasible.write_text(EXAMPLE_INPUT.read_text(encoding="utf-8").replace("min_rest: 6", "min_rest: 30"),
                          encoding="utf-8")
    assert main([str(infeasible), "-n", "2"]) == EXIT_NO_SCHEDULE
