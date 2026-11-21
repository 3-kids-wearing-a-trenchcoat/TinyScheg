"""Tests for the audit's grievances (tools/audit.py, ADR 0048, ADR 0049 and ADR 0051), on hand-built schedules."""
import datetime as dt

import pytest

from audit import (AuditContext, LikeGrievance, LoadGrievance, Rest, WorkerFacts, away_times, build_context,
                   find_grievances, rest_events, rest_grievance, typical_rest, with_history)
from tinyscheg.model.post import Post, ShiftRules
from tinyscheg.model.schedule_input import PreviousSchedule, ScheduleInput, Settings
from tinyscheg.model.shift_generation import all_slots, generate_shifts
from tinyscheg.model.worker import Worker
from tinyscheg.timing.daily_window import DailyWindow
from tinyscheg.timing.datetime_range import DateTimeRange

START = dt.datetime(2025, 1, 1)


def at(hour: int) -> dt.datetime:
    """A moment, in hours from the start of 2025."""
    return START + dt.timedelta(hours=hour)


def context_for(workers: list[Worker], period_hours: int, length: int = 4, crew: int = 1,
                posts: tuple[Post, ...] = ()) -> AuditContext:
    """The audit context of an input with one gate post (shifts of `length` hours, `crew` workers each), or posts."""
    settings = Settings(DateTimeRange(START, at(period_hours)), dt.timedelta(0))
    post_list = posts or (Post("gate", ShiftRules(dt.timedelta(hours=length), (("any", crew),))),)
    schedule_input = ScheduleInput(settings, tuple(workers), post_list)
    shifts = generate_shifts(post_list, settings.period)
    return build_context(schedule_input, shifts, all_slots(shifts))


def names(*workers: str) -> list[Worker]:
    """Workers with no preferences or unavailability."""
    return [Worker(name) for name in workers]


def facts_with_rests(*rests: tuple[float, float]) -> WorkerFacts:
    """A worker's facts with only rests, each (available hours, length of the shift before it)."""
    return WorkerFacts((), 0.0, 0.0, tuple(Rest(index, index + 1, hours, length)
                                           for index, (hours, length) in enumerate(rests)), {}, 0)


# --- availability: only while a post is staffed ---

def test_availability_counts_only_the_hours_when_a_post_is_staffed() -> None:
    day_post = Post("desk", ShiftRules(dt.timedelta(hours=4), (("any", 1),)), DailyWindow(dt.time(8), dt.time(16)))
    workers = [Worker("Anne", unavailable=(DateTimeRange(at(18), at(22)),)),  # away when nothing is staffed
               Worker("Bob", unavailable=(DateTimeRange(at(8), at(12)),))]    # away for half the staffed time
    context = context_for(workers, 24, posts=(day_post,))
    assert context.staffed_availability == (8, 4)


def test_time_between_periods_and_periods_before_joining_are_away() -> None:
    periods = [(DateTimeRange(at(0), at(24)), [Worker("Anne", unavailable=(DateTimeRange(at(2), at(4)),)), None]),
               (DateTimeRange(at(30), at(54)), [Worker("Anne"), Worker("Bob")])]
    assert away_times(periods, 0) == (DateTimeRange(at(2), at(4)), DateTimeRange(at(24), at(30)))
    assert away_times(periods, 1) == (DateTimeRange(at(0), at(30)),)


def test_a_worker_who_joined_is_available_only_from_then() -> None:
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),)))
    then = ScheduleInput(Settings(DateTimeRange(at(0), at(24)), dt.timedelta(0)), tuple(names("Anne", "Bob")), (post,))
    schedule_input = ScheduleInput(Settings(DateTimeRange(at(24), at(48)), dt.timedelta(0)),
                                   tuple(names("Anne", "Bob", "Dana")), (post,),
                                   (PreviousSchedule("day1.yml", then, (0, 1, 0, 1, 0, 1)),))
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    context, _ = with_history(schedule_input, shifts, (0, 1, 2, 0, 1, 2))
    assert context.staffed_availability == (48, 48, 24)


# --- load: hours above the worker's share, in proportion to availability, in the worker's shifts (ADR 0053) ---

def load_of(grievance: LoadGrievance | None) -> tuple[int, float, float] | None:
    """A load grievance's events, extra hours and share, rounded for comparing."""
    return None if grievance is None else (grievance.events, round(grievance.extra_hours, 6), round(grievance.share, 6))


def test_load_has_no_tolerance_the_extra_shift_of_a_2_2_3_split_is_an_event() -> None:
    context = context_for(names("Anne", "Bob", "Cy"), 28)  # 7 shifts of 4 hours: a share of 9.33 hours each
    load = find_grievances(context, (0, 1, 2, 0, 1, 2, 2)).load
    assert load[:2] == (None, None) and load_of(load[2]) == (1, round(12 - 28 / 3, 6), round(28 / 3, 6))


def test_load_is_against_the_workers_own_share_not_against_the_best_off_peer() -> None:
    # 6 shifts of 4 hours each for Anne and Bob (their share), 2 for Cy and 10 for Dana: Anne and Bob have no
    # grievance, though Cy worked 16 hours less; Dana's 16 hours above her share are 4 of her shifts
    context = context_for(names("Anne", "Bob", "Cy", "Dana"), 96)
    owners = [0] * 6 + [1] * 6 + [2] * 2 + [3] * 10
    load = find_grievances(context, tuple(owners)).load
    assert load[:3] == (None, None, None) and load_of(load[3]) == (4, 16.0, 24.0)


def test_the_share_is_in_proportion_to_availability() -> None:
    workers = [Worker("Anne"), Worker("Bob", unavailable=(DateTimeRange(at(0), at(12)),))]  # 24 and 12 hours
    context = context_for(workers, 24)  # 6 shifts of 4 hours: shares of 16 and 8 hours
    assert [load_of(g) for g in find_grievances(context, (0, 0, 0, 1, 1, 1)).load] == [None, (1, 4.0, 8.0)]
    assert find_grievances(context, (0, 0, 0, 0, 1, 1)).load == (None, None)


def two_lengths(period_hours: int, workers: list[Worker], short: int = 2) -> AuditContext:
    """A gate post of `short`-hour shifts and a desk post of 4-hour shifts."""
    posts = (Post("gate", ShiftRules(dt.timedelta(hours=short), (("any", 1),))),
             Post("desk", ShiftRules(dt.timedelta(hours=4), (("any", 1),))))
    return context_for(workers, period_hours, posts=posts)


def assign(context: AuditContext, owners: dict[tuple[str, int], int], default: int) -> tuple[int, ...]:
    """An assignment from (post, start hour) to worker, everything else to the default worker."""
    return tuple(owners.get((context.shifts[slot.shift_index].post.name,
                             round((slot.time.start - START) / dt.timedelta(hours=1))), default)
                 for slot in context.slots)


def test_load_is_hours_alone_whatever_the_number_of_shifts() -> None:
    # Anne's two 2-hour gate shifts against Bob's one 4-hour desk shift: both at their share of 4 hours
    context = two_lengths(4, names("Anne", "Bob"))
    assert find_grievances(context, assign(context, {("desk", 0): 1}, 0)).load == (None, None)


def test_a_shift_counts_when_at_least_half_of_it_is_extra() -> None:
    # Anne's one 4-hour desk shift, against a share of 2 hours (8 hours for 4 workers): half of it is extra, so one
    # event, though no shift of hers fits in the 2 extra hours
    context = two_lengths(4, names("Anne", "Bob", "Cy", "Dana"))
    owners = {("desk", 0): 0, ("gate", 0): 1, ("gate", 2): 2}
    assert [load_of(g) for g in find_grievances(context, assign(context, owners, 3)).load] == [
        (1, 2.0, 2.0), None, None, None]
    # with 3 workers, a share of 2.67 hours: Anne's 1.33 extra hours are less than half her shift, so no event
    context = two_lengths(4, names("Anne", "Bob", "Cy"))
    assert find_grievances(context, assign(context, owners, 2)).load == (None, None, None)


def test_an_hours_excess_counts_the_workers_own_shifts_shortest_first() -> None:
    # Anne the desk 0-12 and the gates 12-16, 16-20 and 20-24 (24 hours) against a share of 16: her 8 extra hours are
    # two of her 4-hour shifts, not also her 12-hour one, of which none is left
    posts = (Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),))),
             Post("desk", ShiftRules(dt.timedelta(hours=12), (("any", 1),))))
    context = context_for(names("Anne", "Bob", "Cy"), 24, posts=posts)
    owners = {("desk", 0): 0, ("gate", 12): 0, ("gate", 16): 0, ("gate", 20): 0, ("gate", 0): 1, ("gate", 4): 1}
    assert load_of(find_grievances(context, assign(context, owners, 2)).load[0]) == (2, 8.0, 16.0)


# --- rest: the available part, per hour of the shift before it, against the typical rest (ADR 0054) ---

def test_a_rest_is_only_its_available_part_per_hour_of_the_shift_before_it() -> None:
    workers = [Worker("Anne", unavailable=(DateTimeRange(at(4), at(6)),)), Worker("Bob")]
    context = context_for(workers, 12, length=2)  # shifts from 0, 2, ... 10
    facts = find_grievances(context, (0, 1, 1, 1, 0, 1)).facts  # Anne 0-2 and 8-10, away 4-6
    assert facts[0].rests == (Rest(0, 4, 4.0, 2.0),) and facts[0].rests[0].per_hour == 2


def test_the_typical_rest_is_the_median_of_every_rest_per_hour_of_the_shift_before_it() -> None:
    facts = (facts_with_rests((4, 2), (6, 2)), facts_with_rests((8, 2)), facts_with_rests((12, 4)))  # 2, 3, 4 and 3
    assert typical_rest(facts) == 3
    assert typical_rest((facts_with_rests(),)) is None


def test_a_rest_after_a_longer_shift_is_shorter() -> None:
    # 6 hours after a 12-hour shift, against a typical rest of 3 hours per hour of the shift before: 30 hours short
    events = rest_events((Rest(0, 1, 6.0, 12.0),), 3.0)
    assert [event.shortfall for event in events] == [pytest.approx(30)]


def test_a_rest_after_a_long_shift_is_judged_at_the_same_rate_as_the_others() -> None:
    # 12 hours after a 6-hour shift is 2 per hour of it; everyone else's 6 hours after a 2-hour shift are 3: 6 hours
    # short of the 18 a shift this long would typically be followed by
    facts = (facts_with_rests((12, 6)), facts_with_rests((6, 2)), facts_with_rests((6, 2)))
    grievance = rest_grievance(facts, 0, typical_rest(facts))
    assert grievance is not None and grievance.typical == 3 and [e.shortfall for e in grievance.events] == [6]
    assert rest_grievance(facts, 1, typical_rest(facts)) is None


def test_a_rest_is_judged_by_the_shift_before_it_not_the_one_after() -> None:
    # Anne's 10 hours between the gate 0-2 and the desk 12-16 are 5 per hour of the shift before them: no shorter than
    # a typical 4, though the shifts around them average 3 hours; against a typical 6, 2 hours short
    context = two_lengths(16, names("Anne", "Bob"))
    facts = find_grievances(context, assign(context, {("gate", 0): 0, ("desk", 12): 0}, 1)).facts
    rest, = facts[0].rests
    assert (rest.hours, rest.shift_hours, rest.per_hour) == (10, 2, 5)
    assert rest_events(facts[0].rests, 4.0) == ()
    assert [event.shortfall for event in rest_events(facts[0].rests, 6.0)] == [2]


def test_the_same_rests_for_everyone_give_no_event_however_short() -> None:
    facts = tuple(facts_with_rests((6, 2), (6, 2)) for _ in range(3))
    assert [rest_grievance(facts, worker, typical_rest(facts)) for worker in range(3)] == [None, None, None]


def test_each_rest_below_the_typical_rest_is_an_event_shortest_first() -> None:
    mine = facts_with_rests((10, 2), (4, 2), (7, 2))
    events = rest_events(mine.rests, 4.0)  # 2 and 3.5 per hour of the shift before are below 4; 5 isn't
    assert [(event.rest.hours, event.shortfall) for event in events] == [(4, 4), (7, 1)]


# --- partners (ADR 0049) ---

def test_each_disliked_person_in_a_shift_is_an_event_and_only_for_who_dislikes() -> None:
    workers = [Worker("Anne", dislikes=frozenset({"Bob", "Cy"})), Worker("Bob"), Worker("Cy"), Worker("Dana")]
    context = context_for(workers, 8, crew=3)  # two shifts of 3
    disliked = find_grievances(context, (0, 1, 2, 0, 1, 3)).disliked
    assert [(event.shift, event.person) for event in disliked[0]] == [(0, 1), (0, 2), (1, 1)]
    assert disliked[1:] == ((), (), ())


def like_context(**likes: set[str]) -> AuditContext:
    """Anne, Bob, Cy and Xena with the given likes, on 6 shifts of 2 workers."""
    workers = [Worker(name, likes=frozenset(likes.get(name, set()))) for name in ("Anne", "Bob", "Cy", "Xena")]
    return context_for(workers, 24, crew=2)


ANNE, BOB, CY, XENA = range(4)


def test_a_missing_like_is_a_shift_with_partners_none_of_whom_the_worker_likes() -> None:
    context = like_context(Anne={"Xena"}, Cy={"Anne", "Bob", "Xena"})
    crews = ((BOB, XENA), (BOB, XENA), (ANNE, CY), (ANNE, XENA), (ANNE, BOB), (XENA, CY))
    grievances = find_grievances(context, tuple(worker for crew in crews for worker in crew))
    # Anne is with Xena in 1 of her 3 shifts: the other 2 are events, whoever else had Xena, and with no peer
    assert grievances.liked[ANNE] == LikeGrievance(ANNE, (2, 4))
    # Cy likes everyone, so is with someone liked in every shift; Bob and Xena like nobody
    assert grievances.liked[BOB] is None and grievances.liked[CY] is None and grievances.liked[XENA] is None
    assert [facts.liked_pairings for facts in grievances.facts] == [1, 0, 2, 0]


def test_a_shift_worked_alone_is_no_missing_like() -> None:
    context = context_for([Worker("Anne", likes=frozenset({"Bob"})), Worker("Bob")], 8)  # two shifts of one worker
    assert find_grievances(context, (0, 1)).liked == (None, None)


def test_a_like_for_someone_who_dislikes_the_worker_doesnt_count() -> None:
    workers = [Worker("Anne", likes=frozenset({"Bob", "Cy"})), Worker("Bob", dislikes=frozenset({"Anne"})),
               Worker("Cy")]
    context = context_for(workers, 8, crew=2)  # two shifts of 2
    assert context.likes == (frozenset({2}), frozenset(), frozenset())
    grievances = find_grievances(context, (0, 1, 0, 2))  # Anne with Bob, then with Cy
    # with Bob, whom she likes but who dislikes her, Anne is with nobody she likes; Bob's dislike stays an event
    assert grievances.liked[0] == LikeGrievance(0, (0,)) and grievances.facts[0].liked_pairings == 1
    assert [(event.shift, event.person) for event in grievances.disliked[1]] == [(0, 0)]
