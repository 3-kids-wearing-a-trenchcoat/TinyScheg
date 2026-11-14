# 0038. A rest counts only the time the worker was available

**Status:** Accepted.

## Context

A rest was the time between two of a worker's shifts on the clock. If the worker was unavailable for part of it
(sick, on leave, on some other duty), that time counted as rest.

The user (2026-11-14): unavailability is neither work nor rest, whatever its reason, which is often ambiguous anyway,
and no reason is to be rewarded or penalized. Workload is measured against available time: a worker available for
24 hours with 2 shifts and one available for 12 with 1 have the same workload. Extended to rest: if A is available
all day and works at 00:00 and 12:00 (2-hour shifts), A rests 10 hours; if B is available 00:00–06:00 and
18:00–24:00 and works at 00:00 and 18:00, that's twice A's work per available hour, yet on the clock B rested 16
hours, more than A. Counting the absence as rest also made it free to put a worker's shifts right before and right
after an absence, a penalty on being unavailable. Not judging such rests at all would leave the same cramming free.

The rest factor ([ADR 0036](0036-rest-targets-from-the-input-convex-per-worker.md)) is already in available time:
each worker's share of free time is their available hours less their fair share of work. With rests on the clock,
the targets and the rests they were compared with weren't in the same terms.

## Decision

**A rest is the time between two consecutive shifts of a worker less their unavailability within it**, in the rest
penalty and in each worker's worst possible deficit. The time between periods of a schedule with a history is
unavailable for everyone ([ADR 0031](0031-history-as-the-filled-part-of-one-schedule.md)), so it's left out the same
way. The hard minimum rest stays on the clock: it's the scheduler's rule of what's legal, and measuring it in
available time could make inputs infeasible.

Each worker's unavailable hours up to each slot's start and end are computed once, before the search, so a rest's
available time is a subtraction, exactly 0 for a worker with no unavailability in it: their rests, and the results
of inputs with no unavailability, are exactly as before. A worker is available for every shift they work, so a new
shift still splits a rest into two whose available times add up to the old one's less the shift: the penalty stays
monotone.

## Consequences

* A rest spanning an absence is judged by the time available around it: after a leave, a shift right after it
  counts as a short rest if the shift right before it was close to it in available time, as it would without the
  leave in between. The same holds for any reason for being away.
* On the benchmark (where one worker in ten has one block of 2, 4 or 8 hours unavailable), results change only on
  inputs with unavailability, and the search is a little faster (28.5 M nodes against 30.5 M). Measured in available
  time, the spread of workers' shortest rests narrows (alone 88 to 74, day 2 70 to 61), with slightly more rests
  under 8 hours (54% to 55%, 38% to 40%), and the gaps in hours and shift counts between peers about the same.
* A test checks that a worker's shifts right before and right after an absence cost more than shifts spread out in
  their available time, although on the clock the first rest is the longer.
