"""Tests for tinyscheg.csp.next_period (ADR 0042): whether a schedule leaves the next period a legal schedule."""
import datetime as dt
import pathlib

import pytest
import yaml

from test_cli import write
from tinyscheg.cli import EXIT_SUCCESS, main
from tinyscheg.csp.next_period import NextPeriodCheck, check_next_period, next_period_input, next_period_offset
from tinyscheg.csp import search as search_module
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.parsing.input_reader import parse_input


def two_medics(medics: int = 2, hours: int = 24) -> dict:
    """
    A night post from 00:00 to 04:00 needing two medics, and a desk from 20:00 to midnight needing one: whoever takes
    the desk can't take the next night's post (minimum rest 6 hours), so with two medics the next period of a 24-hour
    schedule can't be filled, though this one can, and so can the next one alone
    """
    start = dt.datetime(2025, 1, 1)
    return {"settings": {"time": [start.isoformat(), (start + dt.timedelta(hours=hours)).isoformat()], "min_rest": 6},
            "workers": [{"name": f"Medic {index}", "roles": ["medic"]} for index in range(medics)],
            "posts": [{"name": "night", "roles": {"medic": 2}, "length": 4, "time": "00:00-04:00"},
                      {"name": "desk", "roles": {"medic": 1}, "length": 4, "time": "20:00-00:00"}]}


def checked(document: dict, max_nodes: int | None = None) -> NextPeriodCheck:
    """The check after the first legal schedule of an input."""
    schedule_input = parse_input(document)
    problem = build_problem(schedule_input)
    result = find_first_schedule(problem)
    assert result.assignment is not None
    if max_nodes is None:
        return check_next_period(schedule_input, problem, result.assignment)
    return check_next_period(schedule_input, problem, result.assignment, max_nodes)


def test_a_schedule_that_leaves_the_next_period_no_legal_schedule() -> None:
    assert checked(two_medics()) is NextPeriodCheck.NOT_FILLABLE
    # the next period alone, with everyone rested, is the same input, which can be filled
    assert find_first_schedule(build_problem(parse_input(two_medics()))).assignment is not None


def test_a_schedule_that_leaves_the_next_period_fillable() -> None:
    assert checked(two_medics(medics=3)) is NextPeriodCheck.FILLABLE


def test_a_check_that_reaches_its_node_limit_is_undecided(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_module, "PROGRESS_INTERVAL_NODES", 1)  # the limit is checked at every progress report
    assert checked(two_medics(medics=3), max_nodes=1) is NextPeriodCheck.UNDECIDED


def test_the_next_period_is_the_same_hours_a_whole_number_of_days_later() -> None:
    day = parse_input(two_medics())
    assert next_period_offset(day) == dt.timedelta(days=1)  # right after a 24-hour period
    assert next_period_offset(parse_input(two_medics(hours=16))) == dt.timedelta(days=1)  # the next day, same time
    assert next_period_offset(parse_input(two_medics(hours=30))) == dt.timedelta(days=2)
    following = next_period_input(day, (0, 1, 0))
    assert following.settings.period.start == day.settings.period.end
    assert following.settings.period.duration == day.settings.period.duration
    assert following.history[-1].schedule_input == day and following.history[-1].assignment == (0, 1, 0)
    after_that = next_period_input(following, (1, 0, 1))  # the history keeps growing
    assert [previous.assignment for previous in after_that.history] == [(0, 1, 0), (1, 0, 1)]


def test_unavailability_is_repeated_in_the_next_period() -> None:
    document = two_medics(medics=3)
    document["workers"][2]["unavailable"] = [["2025-01-01T10:00", "2025-01-01T12:00"]]
    following = next_period_input(parse_input(document), (0, 1, 0))
    assert following.workers[2].unavailable[0].start == dt.datetime(2025, 1, 2, 10)


def test_the_command_line_warns_when_the_next_period_cant_be_filled(tmp_path: pathlib.Path,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    for medics, warned in ((2, True), (3, False)):
        path = write(tmp_path, yaml.safe_dump(two_medics(medics)), f"medics_{medics}.yml")
        assert main([str(path), "-o", str(tmp_path / f"medics_{medics}.csv"), "--jobs", "1"]) == EXIT_SUCCESS
        error = capsys.readouterr().err
        assert ("warning: after this schedule, the next period with the same parameters "
                "(2025-01-02 00:00–2025-01-03 00:00) has no legal schedule" in error) is warned
