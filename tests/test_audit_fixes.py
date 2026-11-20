"""Tests for the audit's fix search (tools/audit.py, ADR 0048): fixes as nearby schedules, judged only as a whole."""
import datetime as dt
import itertools
from collections import deque

import pytest

from audit import (DISLIKED_PARTNER, LOAD, NO_PERSON, REST, AuditContext, FixesFound, GrievanceKey, NearbyFix,
                   Standing, Step, better_off, build_context, created_by, find_grievances, keep_undominated,
                   search_fixes, standing, with_history)
from schedule_checker import hard_constraint_violations
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


def make_context(workers: list[Worker], posts: tuple[Post, ...], period_hours: int,
                 min_rest: int = 0) -> AuditContext:
    """The audit context of an input."""
    settings = Settings(DateTimeRange(START, at(period_hours)), dt.timedelta(hours=min_rest))
    schedule_input = ScheduleInput(settings, tuple(workers), posts)
    shifts = generate_shifts(posts, settings.period)
    return build_context(schedule_input, shifts, all_slots(shifts))


def one_shift_post(name: str, start: int, crew: int, roles: tuple[tuple[str, int], ...] = ()) -> Post:
    """A post with one 2-hour shift a day, from the given hour, needing `crew` workers (or the given roles)."""
    return Post(name, ShiftRules(dt.timedelta(hours=2), roles or (("any", crew),)),
                DailyWindow(dt.time(start), dt.time(start + 2)))


def trade_context(workers: list[Worker] | None = None) -> AuditContext:
    """
    Shifts at 0-2 (2 workers), 4-6 (1), 8-10 (2) and 12-14 (1), with a minimum rest of 3 hours, so that nobody can
    hold two neighbouring shifts: Anne (who dislikes Bob), Bob and Cy
    """
    posts = (one_shift_post("a", 0, 2), one_shift_post("b", 4, 1), one_shift_post("c", 8, 2),
             one_shift_post("d", 12, 1))
    workers = workers or [Worker("Anne", dislikes=frozenset({"Bob"})), Worker("Bob"), Worker("Cy")]
    return make_context(workers, posts, 14, min_rest=3)


ANNE, BOB, CY = range(3)


def fixes_for(context: AuditContext, assignment: tuple[int, ...], max_changes: int = 3) -> dict[GrievanceKey,
                                                                                                FixesFound]:
    """The fixes the search finds for a schedule."""
    return search_fixes(context, assignment, find_grievances(context, assignment), max_changes)


# --- what a fix is: a legal nearby schedule, judged as a whole ---

def test_a_fix_legal_only_with_all_its_changes_is_found() -> None:
    # Anne and Bob share 0-2 and 8-10, Cy has 4-6 and 12-14: Cy can trade all their shifts with Anne or Bob, though
    # either swap alone would leave someone with neighbouring shifts
    context = trade_context()
    assignment = (ANNE, BOB, CY, ANNE, BOB, CY)
    key = (DISLIKED_PARTNER, ANNE, BOB)
    assert fixes_for(context, assignment, max_changes=1)[key] == FixesFound(None, ())
    fix = fixes_for(context, assignment)[key].harmless
    assert fix is not None and len(fix.steps) == 2 and fix.removes == 2
    traded = list(assignment)
    for step in fix.steps:
        for slot, worker in zip(step.slots, step.workers):
            traded[slot] = worker
    assert sorted(traded) == sorted(assignment)  # a trade: everyone still has two shifts
    assert not any({ANNE, BOB} <= set(traded[slot.index] for slot in shift.slots) for shift in context.shifts)


def test_the_extra_shift_of_a_2_2_3_split_has_only_transfers() -> None:
    context = make_context([Worker("Anne"), Worker("Bob"), Worker("Cy")],
                           (Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),))),), 28)
    assignment = (CY, ANNE, CY, BOB, CY, ANNE, BOB)  # 7 shifts, nobody back to back; Cy has 3
    found = fixes_for(context, assignment)[(LOAD, CY, NO_PERSON)]
    assert found.harmless is None and found.transfers
    assert all(any(kind == LOAD and worker != CY for (kind, worker, _), _ in transfer.creates)
               for transfer in found.transfers)  # someone else gets the extra shift


def test_no_fix_changes_the_history() -> None:
    post = Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),)))
    workers = (Worker("Anne"), Worker("Bob"), Worker("Cy"))
    then = ScheduleInput(Settings(DateTimeRange(at(0), at(24)), dt.timedelta(0)), workers, (post,))
    schedule_input = ScheduleInput(Settings(DateTimeRange(at(24), at(48)), dt.timedelta(0)), workers, (post,),
                                   (PreviousSchedule("day1.yml", then, (0, 1, 0, 1, 0, 2)),))
    shifts = generate_shifts(schedule_input.posts, schedule_input.settings.period)
    context, assignment = with_history(schedule_input, shifts, (0, 2, 0, 2, 0, 1))
    found = search_fixes(context, assignment, find_grievances(context, assignment))
    assert any(fixes.harmless or fixes.transfers for fixes in found.values())
    assert all(slot >= context.fixed_slots for fixes in found.values()
               for fix in ((fixes.harmless,) if fixes.harmless else ()) + fixes.transfers
               for step in fix.steps for slot in step.slots)


def test_a_search_of_no_changes_is_off() -> None:
    context = trade_context()
    assert fixes_for(context, (ANNE, BOB, CY, ANNE, BOB, CY), max_changes=0) == {}


# --- judging a nearby schedule ---

def standing_of(hours: tuple[float, ...], rests: tuple[tuple[float, ...], ...],
                events: dict[GrievanceKey, int] | None = None) -> Standing:
    """A Standing with the given hours and rests per hour, and nobody's shortfalls or partners."""
    return Standing(events or {}, tuple(() for _ in hours), hours, rests, tuple({} for _ in hours))


def test_making_the_peer_worse_off_is_no_fix() -> None:
    # A's shortest rest is 6 hours (per hour of shift: 3) and B's 8 (4); cutting B's to 6 removes A's event, but A
    # gained nothing
    before = standing_of((4, 4), ((3.0,), (4.0,)), {(REST, 0, NO_PERSON): 1})
    after = standing_of((4, 4), ((3.0,), (3.0,)))
    assert not better_off((REST, 0, NO_PERSON), before, after)
    assert better_off((REST, 0, NO_PERSON), before, standing_of((4, 4), ((3.5,), (4.0,))))


def test_better_off_in_load_is_fewer_hours() -> None:
    before = standing_of((6, 4), ((), ()))
    assert better_off((LOAD, 0, NO_PERSON), before, standing_of((4, 6), ((), ())))
    assert not better_off((LOAD, 0, NO_PERSON), before, standing_of((6, 4), ((), ())))  # fewer shifts alone isn't


def test_a_larger_rest_event_is_created_with_a_shorter_rest_even_with_no_more_events() -> None:
    before = Standing({}, ((2.0, 1.0),), (9.0,), ((1.0, 2.0),), ({},))
    after = Standing({}, ((2.5,),), (9.0,), ((0.8, 2.0),), ({},))
    assert created_by(before, after) == ((("larger rest event", 0, NO_PERSON), 1),)


def test_a_grievance_grown_only_because_a_peer_is_better_off_is_not_created() -> None:
    # Bob's rests and shifts are as they were; his rest event grew, and he has a new load event, only because the peer
    # he's measured against now rests longer and works less (ADR 0050)
    before = Standing({(REST, 1, NO_PERSON): 1}, ((), (1.0,)), (6.0, 4.0), ((3.0, 3.0), (2.0,)), ({}, {}))
    after = Standing({(REST, 1, NO_PERSON): 2, (LOAD, 1, NO_PERSON): 1}, ((), (2.0, 0.5)), (4.0, 4.0),
                     ((6.0,), (2.0,)), ({}, {}))
    assert created_by(before, after) == ()


def test_a_shift_given_to_a_worker_who_had_fewer_harms_nobody() -> None:
    context = make_context([Worker("Anne"), Worker("Bob"), Worker("Cy")],
                           (Post("gate", ShiftRules(dt.timedelta(hours=4), (("any", 1),))),), 24)
    assignment = (ANNE, BOB, ANNE, BOB, ANNE, CY)  # 3, 2 and 1 shifts, every rest 4 hours, nobody back to back
    found = fixes_for(context, assignment)[(LOAD, ANNE, NO_PERSON)]
    # Anne's 00:00 to Cy leaves everyone with 2 shifts: Cy works more but has no new grievance, and Anne's and Bob's
    # 4-hour rests now fall short of Cy's 16 only because Cy rests longer (ADR 0050), so it's harmless
    assert found.harmless == NearbyFix((Step((0,), (CY,), (ANNE,)),), 2, ())


def fix_of(size: int, *created: GrievanceKey) -> NearbyFix:
    """A NearbyFix of a given number of changes, creating one event of each grievance given."""
    return NearbyFix(tuple(Step((index,), (0,), (1,)) for index in range(size)), 1, tuple((key, 1) for key in created))


def test_a_transfer_is_dropped_when_another_creates_less_with_no_more_changes() -> None:
    b_load, c_load, c_rest = (LOAD, 1, NO_PERSON), (LOAD, 2, NO_PERSON), (REST, 2, NO_PERSON)
    transfers: list[NearbyFix] = []
    keep_undominated(transfers, fix_of(1, b_load, c_rest))
    keep_undominated(transfers, fix_of(1, c_load))
    keep_undominated(transfers, fix_of(2, c_load, c_rest))  # creates more than the second, with more changes: dropped
    keep_undominated(transfers, fix_of(1, b_load))          # less than the first, as few changes: replaces it
    keep_undominated(transfers, fix_of(2, b_load))          # the same as one with fewer changes: dropped
    assert transfers == [fix_of(1, c_load), fix_of(1, b_load)]


# --- against brute force: every legal schedule within the reach, judged directly ---

def distances(start: tuple[int, ...], context: AuditContext, reach: int) -> dict[tuple[int, ...], int]:
    """
    How many moves and swaps (two slots in different shifts) each schedule is from the start, up to the reach,
    with no regard for legality, roles or availability on the way: the definition the search must meet
    """
    workers = len(context.schedule_input.workers)
    slots = context.slots
    result = {start: 0}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if result[current] == reach:
            continue
        neighbours = [current[:slot] + (worker,) + current[slot + 1:] for slot in range(len(slots))
                      for worker in range(workers) if worker != current[slot]]
        for first, second in itertools.combinations(range(len(slots)), 2):
            if current[first] != current[second] and slots[first].shift_index != slots[second].shift_index:
                swapped = list(current)
                swapped[first], swapped[second] = current[second], current[first]
                neighbours.append(tuple(swapped))
        for neighbour in neighbours:
            if neighbour not in result:
                result[neighbour] = result[current] + 1
                queue.append(neighbour)
    return result


def expected_fixes(context: AuditContext, assignment: tuple[int, ...],
                   reach: int) -> dict[GrievanceKey, tuple[int | None, set]]:
    """
    For each grievance, by brute force: the smallest harmless fix's size, and the transfers (what each creates, and
    its size) that no other one dominates
    """
    before = standing(find_grievances(context, assignment))
    keys = [key for key, count in before.events.items() if count > 0]
    found: dict[GrievanceKey, list[tuple[tuple, int]]] = {key: [] for key in keys}
    for nearby, size in distances(assignment, context, reach).items():
        if size == 0 or hard_constraint_violations(context.schedule_input, context.slots, nearby):
            continue
        after = standing(find_grievances(context, nearby))
        creates = created_by(before, after)
        for key in keys:
            if before.events[key] > after.events.get(key, 0) and better_off(key, before, after):
                found[key].append((creates, size))
    result = {}
    for key, candidates in found.items():
        harmless = min((size for creates, size in candidates if not creates), default=None)
        transfers = {(creates, size) for creates, size in candidates
                     if creates and (harmless is None or size < harmless)}
        undominated = {(creates, size) for creates, size in transfers
                       if not any((other, other_size) != (creates, size) and dict_includes(creates, other)
                                  and other_size <= size for other, other_size in transfers)}
        result[key] = (harmless, undominated)
    return result


def dict_includes(larger: tuple, smaller: tuple) -> bool:
    """True if one set of created grievances (with counts) includes another."""
    counts = dict(larger)
    return all(count <= counts.get(key, 0) for key, count in smaller)


def brute_force_inputs() -> list[AuditContext]:
    """
    Small inputs for checking the search against brute force: the trade input, and one with four workers, partners on
    several sides, a lead role, an absence, and gaps between shifts of 2 hours (less than the minimum rest) and 3
    """
    workers = [Worker("Anne", roles=frozenset({"lead"}), dislikes=frozenset({"Bob"}), likes=frozenset({"Cy"})),
               Worker("Bob", likes=frozenset({"Anne"})),
               Worker("Cy", roles=frozenset({"lead"}), likes=frozenset({"Dana"})),
               Worker("Dana", unavailable=(DateTimeRange(at(9), at(11)),), dislikes=frozenset({"Cy"}))]
    posts = (one_shift_post("a", 0, 2), one_shift_post("b", 4, 0, (("lead", 1),)), one_shift_post("c", 9, 2))
    return [trade_context(), make_context(workers, posts, 11, min_rest=3)]


@pytest.mark.parametrize("input_index", [0, 1])
def test_the_search_finds_what_brute_force_finds(input_index: int) -> None:
    context = brute_force_inputs()[input_index]
    workers = len(context.schedule_input.workers)
    legal = [assignment for assignment in itertools.product(range(workers), repeat=len(context.slots))
             if not hard_constraint_violations(context.schedule_input, context.slots, assignment)]
    assert legal
    for assignment in legal:
        found = fixes_for(context, assignment)
        expected = expected_fixes(context, assignment, 3)
        assert set(found) == set(expected)
        for key, (harmless, transfers) in expected.items():
            fixes = found[key]
            assert (len(fixes.harmless.steps) if fixes.harmless else None) == harmless, (assignment, key)
            assert {(fix.creates, len(fix.steps)) for fix in fixes.transfers} == transfers, (assignment, key)
