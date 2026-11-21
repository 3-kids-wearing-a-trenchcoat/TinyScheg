"""Tests for the worker panel's input files and runner (tools/worker_panel.py, ADR 0052); claude itself isn't run."""
import datetime as dt
import random

import pytest

from audit import AuditContext, build_context
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import ScheduleInput, Settings
from tinyscheg.model.shift_generation import all_slots, generate_shifts
from tinyscheg.model.worker import Worker
from tinyscheg.timing.daily_window import DailyWindow
from tinyscheg.timing.datetime_range import DateTimeRange
from worker_panel import (SAMPLE_PER_SCHEDULE, SYSTEM_PROMPT, claude_command, draw_workers, parse_answer,
                          profile_text, run_panel, schedule_workers, shared_text)

START = dt.datetime(2025, 1, 1)
NAMES = ("Anne", "Bob", "Cy", "Dee")
GATE, DESK = "gate", "desk"


def at(hour: int) -> dt.datetime:
    """A moment, in hours from the start of 2025."""
    return START + dt.timedelta(hours=hour)


def panel_input(absences: bool = True) -> tuple[AuditContext, tuple[int, ...], ScheduleInput]:
    """
    Eight hours with a gate (2-hour shifts, 2 workers of any role) and a desk (4-hour shifts, 1 medic): Anne (a medic,
    who likes Bob and dislikes Cy), Bob, Cy (away 6-8, if absences) and Dee (a medic)
    """
    workers = (Worker("Anne", roles=frozenset({"medic"}), likes=frozenset({"Bob"}), dislikes=frozenset({"Cy"})),
               Worker("Bob"),
               Worker("Cy", unavailable=(DateTimeRange(at(6), at(8)),) if absences else ()),
               Worker("Dee", roles=frozenset({"medic"})))
    posts = (Post(GATE, ShiftRules(dt.timedelta(hours=2), (("any", 2),)), DailyWindow(dt.time(0), dt.time(8))),
             Post(DESK, ShiftRules(dt.timedelta(hours=4), (("medic", 1),)), DailyWindow(dt.time(0), dt.time(8))))
    settings = Settings(DateTimeRange(at(0), at(8)), dt.timedelta(hours=1))
    schedule_input = ScheduleInput(settings, workers, posts)
    shifts = generate_shifts(posts, settings.period)
    context = build_context(schedule_input, shifts, all_slots(shifts))
    gate_crews = {0: (1, 2), 2: (1, 3), 4: (2, 3), 6: (1, 3)}  # by the shift's start hour
    assignment = []
    for shift in context.shifts:
        start = int((shift.time.start - START) / dt.timedelta(hours=1))
        crew = gate_crews[start] if shift.post.name == GATE else ((0,) if start == 0 else (3,))
        assignment += crew
    return context, tuple(assignment), schedule_input


def shared(absences: bool = True) -> str:
    """What every worker of the test input sees."""
    return shared_text(*panel_input(absences))


# --- what a worker sees ---

def test_no_minimum_rest_and_no_even_share_are_shown() -> None:
    text = shared().lower()
    assert "minimum" not in text and "even share" not in text and "1 h apart" not in text


def test_the_workplace_rules_are_stated() -> None:
    text = shared()
    assert "Shifts are a duty: everyone would rather work less, not more." in text
    assert "Work is shared in proportion to availability" in text
    assert "People work together only with the others on the same shift, not with those at other posts." in text
    assert "Every hour counts the same, whatever the time of day." in text
    assert "continues a previous one" not in text  # no history


def test_the_grid_numbers_shifts_by_time_then_post_with_slots_in_the_headers() -> None:
    lines = shared().splitlines()
    assert "| time | gate (2 slots: 2 any role) | desk (1 slot: 1 medic) |" in lines
    assert "| Jan 1 00:00-02:00 | #1 Bob & Cy | #2 Anne |" in lines
    assert "| Jan 1 02:00-04:00 | #3 Bob & Dee | (cont. #2) |" in lines
    assert "| Jan 1 04:00-06:00 | #4 Cy & Dee | #5 Dee |" in lines


def test_only_workers_who_are_away_are_listed() -> None:
    assert "- Cy: Jan 1 06:00 to Jan 1 08:00" in shared().splitlines()
    assert not any(line.startswith(("- Anne:", "- Bob:")) for line in
                   shared().split("## Who is away when")[1].split("## Roles")[0].splitlines())
    assert "Nobody is away during the schedule." in shared(absences=False)


def test_everyones_hours_show_the_share_of_available_time_and_each_shifts_length() -> None:
    lines = shared().splitlines()
    assert "| worker | available | worked | share of available time worked | shifts |" in lines
    assert "| Anne | 8 h | 4 h | 50% | 1 |" in lines
    assert "- Dee: #3 (2 h), #4 (2 h), #5 (4 h), #6 (2 h)" in lines


def test_a_worker_sees_only_their_own_likes_and_dislikes() -> None:
    _, _, schedule_input = panel_input()
    assert "like" not in shared().lower()
    anne, bob = profile_text(schedule_input, "Anne"), profile_text(schedule_input, "Bob")
    assert "You are Anne." in anne and "- Your roles: medic" in anne
    assert "- People you like working with: Bob" in anne and "- People you'd rather not work with: Cy" in anne
    assert "- People you like working with: nobody in particular" in bob and "Cy" not in bob


# --- running the workers ---

def test_claude_runs_with_our_system_prompt_and_nothing_else() -> None:
    command = claude_command("sonnet", "the prompt")
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--system-prompt") + 1] == "the prompt"
    assert command[command.index("--tools") + 1] == "" and command[command.index("--setting-sources") + 1] == ""
    assert {"--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"} <= set(command)
    assert command[command.index("--model") + 1] == "sonnet"


@pytest.mark.parametrize("reply, expected", [
    ('[{"complaint": "x"}]', [{"complaint": "x"}]),
    ('```json\n[{"complaint": "x"}]\n```', [{"complaint": "x"}]),
    ("[]", []),
    ('{"complaint": "x"}', None),
    ("I have nothing to say.", None),
])
def test_the_answer_is_read_as_a_json_list(reply: str, expected: list | None) -> None:
    assert parse_answer(reply) == expected


def test_a_sample_draws_workers_at_random_in_their_order() -> None:
    names = ["A", "B", "C", "D", "E", "F"]
    assert draw_workers(names, None, random.Random(1)) == names
    assert draw_workers(names, 10, random.Random(1)) == names
    drawn = draw_workers(names, SAMPLE_PER_SCHEDULE, random.Random(1))
    assert len(drawn) == SAMPLE_PER_SCHEDULE and drawn == sorted(drawn, key=names.index)
    assert drawn == draw_workers(names, SAMPLE_PER_SCHEDULE, random.Random(1))


def test_a_dry_run_lists_the_workers_of_each_schedule(tmp_path, capsys) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "s-first.md").write_text("the schedule", encoding="utf-8")
    for name in NAMES:
        (inputs / f"s-first-{name}.md").write_text(f"You are {name}.", encoding="utf-8")
    assert schedule_workers(tmp_path, "s-first") == sorted(NAMES)
    run_panel(tmp_path, "r", ["s-first"], "sonnet", 2, 0, dry_run=True)
    printed = capsys.readouterr().out.splitlines()
    assert printed[-1] == "2 workers" and len(printed) == 3
    for line in printed[:2]:
        name = line.split()[1].rstrip(":")
        assert line == (f"s-first {name}: system prompt {len(SYSTEM_PROMPT) + 1 + len('the schedule')} chars, "
                        f"message {len(f'You are {name}.')} chars")
    with pytest.raises(FileNotFoundError):
        schedule_workers(tmp_path, "s-both")


def test_a_rest_shows_the_time_available_then_the_whole_gap() -> None:
    # Anne works 0-2 and 8-10 and is away 4-6: 4 hours of rest, in a 6-hour gap (ADR 0055)
    workers = (Worker("Anne", unavailable=(DateTimeRange(at(4), at(6)),)), Worker("Bob"))
    posts = (Post(GATE, ShiftRules(dt.timedelta(hours=2), (("any", 1),))),)
    settings = Settings(DateTimeRange(at(0), at(12)), dt.timedelta(hours=1))
    schedule_input = ScheduleInput(settings, workers, posts)
    shifts = generate_shifts(posts, settings.period)
    context = build_context(schedule_input, shifts, all_slots(shifts))
    lines = shared_text(context, (0, 1, 1, 1, 0, 1), schedule_input).splitlines()
    assert "  - rest between #1 and #5: 4 h (a 6 h gap, 2 h of it away or between schedules)" in lines
    assert "  - rest between #2 and #3: 0 h" in lines
