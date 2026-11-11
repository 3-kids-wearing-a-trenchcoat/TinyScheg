"""Tests for tinyscheg.model.shift_generation."""
import datetime as dt
import pathlib

from tinyscheg.model.post import Post, ShiftRules, Variation
from tinyscheg.model.shift_generation import all_slots, generate_shifts, segments
from tinyscheg.parsing.input_reader import read_input
from tinyscheg.timing.daily_window import DailyWindow
from tinyscheg.timing.datetime_range import DateTimeRange

EXAMPLE_INPUT = pathlib.Path(__file__).parent.parent / "exampleInput.yml"


def at(day: int, hour: int) -> dt.datetime:
    """A datetime on 2025-01-<day> at hour:00."""
    return dt.datetime(2025, 1, day, hour)


def span(day: int, start_hour: int, end_day: int, end_hour: int) -> DateTimeRange:
    """A range from 2025-01-<day> start_hour:00 to 2025-01-<end_day> end_hour:00."""
    return DateTimeRange(at(day, start_hour), at(end_day, end_hour))


def rules(hours: float, *roles: tuple[str, int]) -> ShiftRules:
    """Shift rules of the given length, needing one "any" worker if no roles are given."""
    return ShiftRules(dt.timedelta(hours=hours), roles or (("any", 1),))


def post(name: str, shift_rules: ShiftRules, window: str | None = None,
         *variations: tuple[str, ShiftRules]) -> Post:
    """A post with an optional daily window and (window, rules) variations."""
    return Post(name, shift_rules, DailyWindow.parse(window) if window else None,
                tuple(Variation(DailyWindow.parse(text), varied) for text, varied in variations))


def hours(shifts: tuple, post_name: str) -> list[tuple[int, int, int, int]]:
    """A post's shift times as (start day, start hour, end day, end hour)."""
    return [(shift.time.start.day, shift.time.start.hour, shift.time.end.day, shift.time.end.hour)
            for shift in shifts if shift.post.name == post_name]


# --- segments ---

def test_variation_splits_the_day() -> None:
    general, night = rules(3), rules(3, ("security", 1), ("any", 1))
    gate = post("gate", general, None, ("19:00-07:00", night))
    assert segments(gate, span(1, 0, 2, 12)) == [
        (span(1, 0, 1, 7), night),   # the night that started the day before the period
        (span(1, 7, 1, 19), general),
        (span(1, 19, 2, 7), night),
        (span(2, 7, 2, 12), general),
    ]


def test_variation_only_applies_while_the_post_is_active() -> None:
    general, evening = rules(4), rules(2)
    desk = post("desk", general, "08:00-20:00", ("18:00-22:00", evening))
    assert segments(desk, span(1, 0, 2, 0)) == [(span(1, 8, 1, 18), general), (span(1, 18, 1, 20), evening)]


def test_full_day_window_has_a_daily_boundary() -> None:
    gate = post("gate", rules(4), "06:00-06:00")
    assert [segment for segment, _ in segments(gate, span(1, 0, 3, 0))] == [
        span(1, 0, 1, 6), span(1, 6, 2, 6), span(2, 6, 3, 0)]


# --- shifts ---

def test_example_gate_shifts_restart_at_variation_edges() -> None:
    night = rules(3, ("security", 1), ("any", 1))
    gate = post("front gate", rules(3), None, ("19:00-07:00", night))
    shifts = generate_shifts([gate], span(1, 0, 2, 0))
    assert hours(shifts, "front gate") == [
        (1, 0, 1, 3), (1, 3, 1, 6), (1, 6, 1, 7),                  # night, the last one cut off at 07:00
        (1, 7, 1, 10), (1, 10, 1, 13), (1, 13, 1, 16), (1, 16, 1, 19),
        (1, 19, 1, 22), (1, 22, 2, 0),                             # cut off at the period's end
    ]
    assert [len(shift.slots) for shift in shifts] == [2, 2, 2, 1, 1, 1, 1, 2, 2]


def test_daily_window_shifts() -> None:
    shifts = generate_shifts([post("desk", rules(4), "08:00-20:00")], span(1, 0, 2, 0))
    assert hours(shifts, "desk") == [(1, 8, 1, 12), (1, 12, 1, 16), (1, 16, 1, 20)]


def test_period_starting_inside_the_window() -> None:
    shifts = generate_shifts([post("desk", rules(4), "08:00-20:00")], span(1, 10, 2, 0))
    assert hours(shifts, "desk") == [(1, 10, 1, 14), (1, 14, 1, 18), (1, 18, 1, 20)]


def test_window_opened_the_day_before() -> None:
    shifts = generate_shifts([post("night watch", rules(4), "19:00-07:00")], span(1, 0, 2, 0))
    assert hours(shifts, "night watch") == [(1, 0, 1, 4), (1, 4, 1, 7), (1, 19, 1, 23), (1, 23, 2, 0)]


def test_variation_with_no_workers_closes_the_post() -> None:
    closed = ShiftRules(dt.timedelta(hours=4), ())
    shifts = generate_shifts([post("desk", rules(4), None, ("12:00-13:00", closed))], span(1, 8, 1, 18))
    assert hours(shifts, "desk") == [(1, 8, 1, 12), (1, 13, 1, 17), (1, 17, 1, 18)]


def test_stable_order_across_posts_and_roles() -> None:
    gate = post("gate", rules(2, ("supervisor", 1), ("any", 2)))
    desk = post("desk", rules(4))
    shifts = generate_shifts([gate, desk], span(1, 0, 1, 4))
    assert [(shift.post.name, shift.time) for shift in shifts] == [
        ("gate", span(1, 0, 1, 2)),
        ("desk", span(1, 0, 1, 4)),  # same start, later end
        ("gate", span(1, 2, 1, 4)),
    ]
    assert [shift.index for shift in shifts] == [0, 1, 2]
    slots = all_slots(shifts)
    assert [slot.index for slot in slots] == list(range(7))
    assert [slot.role for slot in shifts[0].slots] == ["supervisor", "any", "any"]
    for shift in shifts:
        for slot in shift.slots:
            assert slot.shift_index == shift.index
            assert slot.post == shift.post and slot.time == shift.time


def test_same_times_are_ordered_by_post_position() -> None:
    first, second = post("b", rules(4)), post("a", rules(4))
    shifts = generate_shifts([first, second], span(1, 0, 1, 4))
    assert [shift.post.name for shift in shifts] == ["b", "a"]


def test_generation_is_deterministic() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    period = schedule_input.settings.period
    assert generate_shifts(schedule_input.posts, period) == generate_shifts(schedule_input.posts, period)


def test_example_input_counts() -> None:
    schedule_input = read_input(EXAMPLE_INPUT)
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    # front gate: 13 night shifts (2 workers each) and 12 day shifts (1 each) over 3 days; desk: 3 shifts a day
    assert len(hours(shifts, "front gate")) == 25
    assert len(hours(shifts, "desk")) == 9
    assert len(all_slots(shifts)) == 13 * 2 + 12 + 9
