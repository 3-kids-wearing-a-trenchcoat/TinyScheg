"""Tests for tinyscheg.parsing.input_reader."""
import datetime as dt
import pathlib
import textwrap

import pytest

from tinyscheg.model.schedule_input import ScoringParameters
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.parsing.validation import InputError
from tinyscheg.timing.daily_window import DailyWindow
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"

MINIMAL = """
settings:
  time: ["2025-01-01", "2025-01-02"]
workers:
  - name: "Anne"
posts:
  - name: "desk"
    roles: {any: 1}
    length: 4
"""


def write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    """Write an input file and return its path."""
    path = tmp_path / "input.yml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def problems_of(tmp_path: pathlib.Path, text: str) -> tuple[str, ...]:
    """The problems reported for an invalid input."""
    with pytest.raises(InputError) as caught:
        read_input(write(tmp_path, text))
    return caught.value.problems


# --- valid input ---

def test_example_input() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    settings = schedule_input.settings
    assert settings.period == DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 4))
    assert settings.min_rest == dt.timedelta(hours=6)

    assert [worker.name for worker in schedule_input.workers] == ["Jack", "Jill", "Jeff", "Anne", "Gilgamesh",
                                                                  "Enkidu", "Ninsun", "Shamhat", "Siduri"]
    jack, jill, jeff, anne = schedule_input.workers[:4]
    assert jack.roles == frozenset({"supervisor", "other"})
    assert jack.unavailable[0] == DateTimeRange(dt.datetime(2025, 1, 1, 4), dt.datetime(2025, 1, 1, 6))
    assert jack.likes == frozenset({"Jill"})
    assert jill.unavailable == (DateTimeRange(dt.datetime(2025, 1, 3), dt.datetime(2025, 1, 4)),)
    assert jeff.dislikes == frozenset({"Jack", "Jill"})
    assert anne == Worker("Anne")

    gate, desk = schedule_input.posts
    assert gate.window is None
    assert gate.rules.length == dt.timedelta(hours=3)
    assert gate.rules.roles == (("any", 1),)
    (night,) = gate.variations
    assert night.window == DailyWindow.parse("19:00-07:00")
    assert night.rules.length == dt.timedelta(hours=3)  # inherited from the post
    assert night.rules.roles == (("security", 1), ("any", 1))
    assert desk.window == DailyWindow.parse("08:00-20:00")
    assert desk.rules.roles == (("supervisor", 1),)


def test_minimal_input_uses_defaults(tmp_path: pathlib.Path) -> None:
    schedule_input = read_input(write(tmp_path, MINIMAL))
    assert schedule_input.settings.min_rest == dt.timedelta(hours=6)
    assert schedule_input.workers == (Worker("Anne"),)


def test_empty_optional_fields_count_as_empty(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('- name: "Anne"', '- name: "Anne"\n    roles:\n    likes:\n    unavailable:')
    assert read_input(write(tmp_path, text)).workers == (Worker("Anne"),)


def test_unquoted_dates_are_accepted(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('["2025-01-01", "2025-01-02"]', "[2025-01-01, 2025-01-02T12:00:00]")
    period = read_input(write(tmp_path, text)).settings.period
    assert period == DateTimeRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 2, 12))


def test_non_latin_names(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('"Anne"', '"ענבל"').replace('"desk"', '"ש.ג."')
    schedule_input = read_input(write(tmp_path, text))
    assert schedule_input.workers[0].name == "ענבל"
    assert schedule_input.posts[0].name == "ש.ג."


def test_variation_inherits_and_overrides(tmp_path: pathlib.Path) -> None:
    text = MINIMAL + textwrap.indent(textwrap.dedent("""
        variations:
          - time: "20:00-08:00"
            length: 6
          - time: "12:00-13:00"
            roles: {}
        """), "    ")
    first, second = read_input(write(tmp_path, text)).posts[0].variations
    assert first.rules.length == dt.timedelta(hours=6) and first.rules.roles == (("any", 1),)
    assert second.rules.length == dt.timedelta(hours=4) and second.rules.workers_needed == 0


def test_fractional_lengths(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace("length: 4", "length: 2.5")
    assert read_input(write(tmp_path, text)).posts[0].rules.length == dt.timedelta(hours=2, minutes=30)


# --- invalid input ---

def test_invalid_yaml(tmp_path: pathlib.Path) -> None:
    (problem,) = problems_of(tmp_path, "settings: [unclosed")
    assert problem.startswith("not valid YAML")


@pytest.mark.parametrize("text", ["", "- just a list"])
def test_not_a_mapping(tmp_path: pathlib.Path, text: str) -> None:
    assert len(problems_of(tmp_path, text)) == 1


def test_missing_sections(tmp_path: pathlib.Path) -> None:
    problems = problems_of(tmp_path, "workers: []")
    assert "the input: missing required field 'settings'" in problems
    assert "workers: must be a non-empty list" in problems
    assert "the input: missing required field 'posts'" in problems


def test_unknown_fields(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('- name: "Anne"', '- name: "Anne"\n    unavailble: []')
    (problem,) = problems_of(tmp_path, text)
    assert problem.startswith("worker #1: unknown field 'unavailble'")


def test_missing_worker_name(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('- name: "Anne"', '- roles: ["x"]')
    assert problems_of(tmp_path, text) == ("worker #1, name: is required",)


@pytest.mark.parametrize("replacement, expected", [
    ("length: 0", 'post #1 ("desk"), length: must be more than 0 hours'),
    ("length: true", 'post #1 ("desk"), length: must be a number of hours'),
    ("length: four", 'post #1 ("desk"), length: must be a number of hours'),
    ("length: 4\n    time: \"25:00-07:00\"", 'post #1 ("desk"), time: invalid time window'),
    ("length: 4\n    roles: {any: -1}", 'post #1 ("desk"), roles: the count for role'),
])
def test_invalid_post_fields(tmp_path: pathlib.Path, replacement: str, expected: str) -> None:
    text = MINIMAL.replace("    roles: {any: 1}\n", "    roles: {any: 1}\n" if "roles" not in replacement else "")
    text = text.replace("length: 4", replacement)
    problems = problems_of(tmp_path, text)
    assert len(problems) == 1 and problems[0].startswith(expected), problems


def test_negative_min_rest(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('time: ["2025-01-01", "2025-01-02"]', 'time: ["2025-01-01", "2025-01-02"]\n  min_rest: -1')
    assert problems_of(tmp_path, text) == ("settings, min_rest: must be at least 0 hours, got -1",)


def test_bad_unavailability_names_the_range(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('- name: "Anne"', '- name: "Anne"\n    unavailable:\n      - ["2025-01-01", "oops"]')
    (problem,) = problems_of(tmp_path, text)
    assert problem.startswith('worker #1 ("Anne"), unavailable: range #1: could not parse date-time \'oops\'')


def test_bad_variation_is_located(tmp_path: pathlib.Path) -> None:
    text = MINIMAL + "    variations:\n      - roles: {any: 2}\n"
    assert problems_of(tmp_path, text) == ('post #1 ("desk"), variation #1, time: is required',)


def test_structural_problems_are_collected(tmp_path: pathlib.Path) -> None:
    text = """
    settings:
      time: ["2025-01-02", "2025-01-01"]
    workers:
      - name: 7
      - name: "Bob"
        roles: "boss"
    posts:
      - name: "desk"
        roles: {any: 1}
        length: -3
    """
    problems = problems_of(tmp_path, text)
    assert len(problems) == 4, problems


def test_validation_runs_after_structure(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('- name: "Anne"', '- name: "Anne"\n    likes: ["Nobody"]')
    assert problems_of(tmp_path, text) == ('worker #1 ("Anne"), likes: unknown worker "Nobody"',)


# --- scoring settings ---

def with_scoring(text: str) -> str:
    """MINIMAL with a scoring section in its settings."""
    return MINIMAL.replace('  time: ["2025-01-01", "2025-01-02"]\n',
                           '  time: ["2025-01-01", "2025-01-02"]\n  scoring:\n' + textwrap.indent(text, "    "))


def test_scoring_defaults_when_omitted(tmp_path: pathlib.Path) -> None:
    assert read_input(write(tmp_path, MINIMAL)).settings.scoring == ScoringParameters()


def test_scoring_overrides(tmp_path: pathlib.Path) -> None:
    text = with_scoring("weights: {likes: 1, workload: 2, rest: 1}\nworkload_power: 3\nrest_factor: 2.5\n"
                        "neutral_partner: 0.5\n")
    scoring = read_input(write(tmp_path, text)).settings.scoring
    assert scoring == ScoringParameters(1, 2, 1, workload_power=3, rest_factor=2.5, neutral_partner=0.5)


def test_omitted_weights_keep_their_defaults(tmp_path: pathlib.Path) -> None:
    scoring = read_input(write(tmp_path, with_scoring("weights: {likes: 0}\n"))).settings.scoring
    assert scoring == ScoringParameters(likes_weight=0)
    assert scoring.workload_weight == pytest.approx(2 / 3)


def test_empty_scoring_section_keeps_the_defaults(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('  time: ["2025-01-01", "2025-01-02"]\n',
                           '  time: ["2025-01-01", "2025-01-02"]\n  scoring:\n')
    assert read_input(write(tmp_path, text)).settings.scoring == ScoringParameters()


def test_every_invalid_scoring_field_is_reported(tmp_path: pathlib.Path) -> None:
    text = with_scoring("weights: {likes: -1, wrokload: 1}\nworkload_power: 1\nrest_factor: fast\n"
                        "neutal_partner: 0.5\n")
    problems = problems_of(tmp_path, text)
    assert len(problems) == 5, problems
    assert any(problem.startswith("settings, scoring: unknown field 'neutal_partner'") for problem in problems)
    assert any(problem.startswith("settings, scoring, weights: unknown field 'wrokload'") for problem in problems)
    assert "settings, scoring: the likes weight must be at least 0, got -1" in problems
    assert "settings, scoring: workload_power must be a whole number of at least 2, got 1" in problems
    assert "settings, scoring: rest_factor must be a number, got 'fast'" in problems


def test_all_zero_weights(tmp_path: pathlib.Path) -> None:
    text = with_scoring("weights: {likes: 0, workload: 0, rest: 0}\n")
    assert problems_of(tmp_path, text) == ("settings, scoring: the weights must not all be 0",)


def test_scoring_must_be_a_mapping(tmp_path: pathlib.Path) -> None:
    text = MINIMAL.replace('  time: ["2025-01-01", "2025-01-02"]\n',
                           '  time: ["2025-01-01", "2025-01-02"]\n  scoring: 3\n')
    assert problems_of(tmp_path, text) == ("settings, scoring: must be a mapping of fields",)
