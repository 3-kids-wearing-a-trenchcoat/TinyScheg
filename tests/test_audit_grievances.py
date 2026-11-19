"""Tests for the audit's grievances (tools/audit.py, ADR 0048 and ADR 0049), on hand-built schedules, one per decision."""
import datetime as dt

import pytest

from audit import (AuditContext, LikeGrievance, LoadGrievance, MissingLike, Rest, WorkerFacts, away_times,
                   build_context, find_grievances, rest_events, rest_grievance, with_history)
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
    """A worker's facts with only rests, each (available hours, mean length of the shifts around it)."""
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


# --- load: whole extra shifts against the best-off peer, scaled down to the worker's availability ---

def test_load_has_no_tolerance_the_extra_shift_of_a_2_2_3_split_is_an_event() -> None:
    context = context_for(names("Anne", "Bob", "Cy"), 28)  # 7 shifts of 4 hours
    load = find_grievances(context, (0, 1, 2, 0, 1, 2, 2)).load
    assert load == (None, None, LoadGrievance(2, 0, 1, 2.0, 8.0))


def test_load_is_against_the_best_off_peer_not_once_per_peer() -> None:
    context = context_for(names("Anne", "Bob", "Cy", "Dana"), 28)
    load = find_grievances(context, (0, 0, 0, 0, 1, 1, 2)).load  # 4, 2, 1 and 0 shifts
    assert load[0] == LoadGrievance(0, 3, 4, 0.0, 0.0)  # against Dana's none, not 2 + 3 + 4 against each


def test_a_peers_load_is_scaled_down_to_the_workers_availability_never_up() -> None:
    workers = [Worker("Anne"), Worker("Bob", unavailable=(DateTimeRange(at(0), at(12)),))]  # 24 and 12 hours
    context = context_for(workers, 24)  # shifts from 0, 4, ... 20
    # Anne's 3 shifts count as 1.5 against Bob's 3: one whole extra shift; Bob, available less, is no peer of Anne's
    assert find_grievances(context, (0, 0, 0, 1, 1, 1)).load == (None, LoadGrievance(1, 0, 1, 1.5, 6.0))
    # Anne's 4 shifts count as 2 against Bob's 2: none, and none for Anne, whatever her 4 against his 2
    assert find_grievances(context, (0, 0, 0, 0, 1, 1)).load == (None, None)


def mixed_lengths(period_hours: int) -> AuditContext:
    """Anne, Bob and Cy, a gate post of 4-hour shifts and a desk post of 12-hour shifts."""
    posts = (Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),))),
             Post("desk", ShiftRules(dt.timedelta(hours=12), (("any", 1),))))
    return context_for(names("Anne", "Bob", "Cy"), period_hours, posts=posts)


def assign(context: AuditContext, owners: dict[tuple[str, int], int], default: int) -> tuple[int, ...]:
    """An assignment from (post, start hour) to worker, everything else to the default worker."""
    return tuple(owners.get((context.shifts[slot.shift_index].post.name,
                             round((slot.time.start - START) / dt.timedelta(hours=1))), default)
                 for slot in context.slots)


def test_load_is_more_only_by_one_measure_and_no_less_by_the_other() -> None:
    context = mixed_lengths(12)  # Cy the gate 0-4, Bob the desk 0-12, Anne the gate 4-8 and 8-12
    load = find_grievances(context, assign(context, {("gate", 0): 2, ("desk", 0): 1}, 0)).load
    # Anne's 2 shifts (8 hours) against Bob's 1 (12 hours): more shifts, fewer hours, neither did more; Bob's 8 hours
    # more than Cy, in as many shifts, fit none of his own shifts: no event; Anne against Cy, one shift more
    assert load == (LoadGrievance(0, 2, 1, 1.0, 4.0), None, None)


def test_an_hours_excess_counts_the_workers_own_shifts_shortest_first() -> None:
    context = mixed_lengths(24)
    # Anne the desk 0-12 and the gate 12-16 (16 hours), Bob the gates 0-4 and 4-8 (8 hours), in as many shifts:
    # 8 hours more fit Anne's 4-hour shift, not also her 12-hour one, so 1 event (8 / 4 would have said 2)
    assignment = assign(context, {("desk", 0): 0, ("gate", 12): 0, ("gate", 0): 1, ("gate", 4): 1}, 2)
    assert find_grievances(context, assignment).load[0] == LoadGrievance(0, 1, 1, 2.0, 8.0)


# --- rest: the available part, per hour of the shifts around it, rest by rest against the best-off peer ---

def test_a_rest_is_only_its_available_part_per_hour_of_the_shifts_around_it() -> None:
    workers = [Worker("Anne", unavailable=(DateTimeRange(at(4), at(6)),)), Worker("Bob")]
    context = context_for(workers, 12, length=2)  # shifts from 0, 2, ... 10
    facts = find_grievances(context, (0, 1, 1, 1, 0, 1)).facts  # Anne 0-2 and 8-10, away 4-6
    assert facts[0].rests == (Rest(0, 4, 4.0, 2.0),) and facts[0].rests[0].per_hour == 2


def test_a_rest_between_longer_shifts_is_shorter() -> None:
    # 6 hours between a 12-hour and a 2-hour shift (mean 7) against 6 hours between two 2-hour shifts: 15 hours short
    events = rest_events((Rest(0, 1, 6.0, 7.0),), (Rest(0, 1, 6.0, 2.0),))
    assert [event.shortfall for event in events] == [pytest.approx(15)]


def test_the_same_rests_for_everyone_give_no_event_whatever_their_order_in_time() -> None:
    assert rest_events(facts_with_rests((4, 2), (10, 2)).rests, facts_with_rests((10, 2), (4, 2)).rests) == ()


def test_rests_are_compared_shortest_with_shortest_up_to_the_smaller_number() -> None:
    mine = facts_with_rests((10, 2), (4, 2), (12, 2))
    theirs = facts_with_rests((8, 2), (6, 2))
    events = rest_events(mine.rests, theirs.rests)  # 4 against 6, 10 against 8; the 12 has nothing in its place
    assert [(event.rest.hours, event.peer_rest.hours, event.shortfall) for event in events] == [(4, 6, 2)]


def test_the_rest_peer_is_the_one_giving_the_most_events_then_the_largest() -> None:
    facts = (facts_with_rests((4, 2), (6, 2)),
             facts_with_rests((5, 2), (7, 2)),   # 2 events of 1 hour
             facts_with_rests((10, 2)),          # 1 event of 6 hours
             facts_with_rests((6, 2), (8, 2)))   # 2 events of 2 hours: the strongest case
    grievance = rest_grievance(facts, 0)
    assert grievance is not None and grievance.peer == 3 and [e.shortfall for e in grievance.events] == [2, 2]
    assert rest_grievance(facts, 2) is None  # the best rested has none


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


def test_a_missing_like_is_judged_by_the_workers_own_likes_on_the_peers_shifts() -> None:
    context = like_context(Anne={"Xena"}, Cy={"Anne", "Bob", "Xena"})
    # Bob shares 2 shifts with Xena, Cy 1, Anne none; each has 3 shifts
    crews = ((BOB, XENA), (BOB, XENA), (ANNE, CY), (ANNE, CY), (ANNE, BOB), (XENA, CY))
    grievances = find_grievances(context, tuple(worker for crew in crews for worker in crew))
    assert grievances.liked[ANNE] == LikeGrievance(ANNE, BOB, (MissingLike(XENA, 2, 0, (0, 1), 2.0),))
    # Cy likes everyone and is with someone liked in every shift, which makes nobody else aggrieved: Bob likes nobody
    assert grievances.liked[BOB] is None and grievances.liked[XENA] is None
    assert [facts.liked_pairings for facts in grievances.facts] == [0, 0, 3, 0]


def test_a_peers_pairings_are_scaled_down_to_the_workers_shifts_never_up() -> None:
    context = like_context(Anne={"Xena"})
    crews = ((BOB, XENA), (BOB, XENA), (BOB, XENA), (BOB, XENA), (ANNE, CY), (ANNE, CY))
    liked = find_grievances(context, tuple(worker for crew in crews for worker in crew)).liked
    assert liked[ANNE] == LikeGrievance(ANNE, BOB, (MissingLike(XENA, 2, 0, (0, 1, 2, 3), 2.0),))  # 4 x 2/4
    crews = ((BOB, XENA), (ANNE, CY), (ANNE, CY), (ANNE, CY), (ANNE, CY), (CY, XENA))
    liked = find_grievances(context, tuple(worker for crew in crews for worker in crew)).liked
    assert liked[ANNE] == LikeGrievance(ANNE, BOB, (MissingLike(XENA, 1, 0, (0,), 1.0),))  # Bob's 1, as it is
