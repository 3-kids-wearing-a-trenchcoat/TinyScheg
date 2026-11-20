"""Tests for tools/audit_sample.py."""
import pathlib

import pytest

from audit import DISLIKED_PARTNER, KIND_ORDER, LOAD, MISSING_LIKE, REST
from audit_sample import (EXIT_NO_SCHEDULE, EXIT_SUCCESS, Sample, disagreements, main, ranks, report,
                          shuffled_schedule, spearman, take_samples)
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


def sample(seed: int, penalty: float, harmless: dict[str, int] | None = None) -> Sample:
    """A sample whose only events are those with a harmless fix given, by kind."""
    measures: dict[str, dict[str, float]] = {}
    for kind in KIND_ORDER:
        count = (harmless or {}).get(kind, 0)
        measures[kind] = {"harmless": count, "most": count, "events": count}
    for kind in (LOAD, REST):
        measures[kind] |= {"hours_harmless": 0.0, "hours_most": 0.0, "hours": 0.0}
    return Sample(seed, (seed,), Penalty(penalty, 0, 0, 0), measures)


def test_disagreements_are_the_best_by_penalty_still_with_a_harmless_fix_kind_by_kind() -> None:
    samples = [sample(seed, float(seed), {LOAD: 1}) for seed in range(8)]
    # the best quarter of eight is seeds 0 and 1, both with a load event that has a harmless fix
    assert {kind: [found.seed for found in found_samples] for kind, found_samples in disagreements(samples).items()} \
        == {LOAD: [0, 1], REST: [], DISLIKED_PARTNER: [], MISSING_LIKE: []}
    samples[0] = sample(0, 0.0, {MISSING_LIKE: 2})
    assert [found.seed for found in disagreements(samples)[MISSING_LIKE]] == [0]
    assert [found.seed for found in disagreements(samples)[LOAD]] == [1]


def test_the_report_correlates_the_penalty_with_each_kind_never_adding_kinds() -> None:
    samples = [sample(0, 1.0, {LOAD: 0}), sample(1, 2.0, {LOAD: 1}), sample(2, 3.0, {LOAD: 2, REST: 1})]
    text = report(samples)
    assert text.startswith("each kind's events (with a harmless fix); fixes searched up to 3 changes\nseed   0:")
    assert "  load: 1 / 1" in text and "  disliked partner: n/a (constant) / n/a (constant)" in text
    assert "  rest: 0.87 / 0.87; in h short: n/a (constant) / n/a (constant)" in text
    assert "  load: 1 / 1; in h more: n/a (constant) / n/a (constant)" in text


def test_command_line(capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path) -> None:
    assert len(take_samples(read_input(EXAMPLE_INPUT), 2)) == 2
    assert main([str(EXAMPLE_INPUT), "-n", "2"]) == EXIT_SUCCESS
    assert "2 samples" in capsys.readouterr().out
    infeasible = tmp_path / "input.yml"
    infeasible.write_text(EXAMPLE_INPUT.read_text(encoding="utf-8").replace("min_rest: 6", "min_rest: 30"),
                          encoding="utf-8")
    assert main([str(infeasible), "-n", "2"]) == EXIT_NO_SCHEDULE
