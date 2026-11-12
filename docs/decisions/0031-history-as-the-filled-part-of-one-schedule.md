# 0031. History as the already-filled part of one schedule

**Status:** Accepted. Amends [0029](0029-schedule-history-input.md) (point 6) and
[0030](0030-history-in-scoring.md) (points 1–3).

## Context

[ADR 0029](0029-schedule-history-input.md) had the minimum rest after each worker's last history shift treated as
unavailability, and [ADR 0030](0030-history-in-scoring.md) scored the history and the new schedule as one, but with
special cases: the new period's own normalization, and history pairings and rests left out. Reviewing the plan on
2026-11-12, the user put it more simply: time already worked is assigned time, not unavailability, and a schedule
with a history is to be treated as though the search started midway through a from-scratch schedule. Asked whether
anything beyond computing everything from scratch for the given part, then searching and incrementing as usual, was
needed, the answer was no special handling in the scoring or the search at all.

## Decision

**A schedule with a history is one schedule, from the history's start to the new period's end, already filled up to
the new period.** Everything is computed for it exactly as for a schedule made from scratch.

1. **The history's shifts are filled slots.** They come first in the stable order, generated from each previous
   input (whose posts and hours may differ), with their workers, then the new period's shifts. The search starts
   with them filled and fills the rest. The minimum rest across the boundary follows from the ordinary difference
   constraints between a history slot and a new one, applied to the new slots' domains as forward checking from a
   filled slot would: nothing is marked as unavailability.
2. **History slots keep their workers whatever the current rules,** and aren't constrained with each other: they're
   what happened. Slots of workers who have left are dropped.
3. **Each worker's availability over the whole schedule** is what it was in each period, from that period's input:
   a worker who wasn't in a history input (they joined later) was unavailable during it, and the time between
   periods is unavailable for everyone, so it counts as neither work nor availability.
4. **Scoring is that of the whole schedule, from scratch.** The constants (availability, packable maximum, worst rest
   deficit, mean slot length, number of shared slots, normalizations) are computed over the whole schedule, with the
   current input's settings and scoring parameters. History pairings and rests are scored like any others; they're
   the same in every completion, so they change no choice. Incremental scoring starts from a from-scratch
   calculation of the filled part, then increments as usual.
5. **Only the new period is written.** The output covers the new period's shifts; the penalty reported is that of
   the whole schedule.

This replaces ADR 0029's point 6 (minimum rest as unavailability) and ADR 0030's special cases: the normalization
over the new period alone (point 1), and leaving history rests and pairings out (points 2 and 3), and each history
schedule's own mean slot length for load (point 1). The rest of both stands: previous inputs with their schedule
files, availability from each history input (being away is never a debt), and no decay of older history.

Rejected:

* **The minimum rest as unavailability, and history-specific scoring** (ADRs 0029 and 0030 as first written): the
  same results at the boundary, but more special cases, in the search and in the scoring, to get wrong.

## Consequences

* The scoring and the search have no history-specific logic: the from-scratch functions, the bound and incremental
  scoring work on the whole schedule as they would on any partly filled one, and the brute-force tests apply as
  they are.
* ADR 0030 kept the new period's normalization so that the workload term wouldn't shrink against likes and rest as
  history grows. Normalized over the whole schedule, all three terms shrink with a longer history, so their balance
  roughly holds, though not exactly: each is normalized by something different (shared slots, availability, worst
  rest deficits). A long history could shift the balance somewhat; the audit across schedules is to check it.
* A short schedule can still decline to make up for the history when that would cost rests: in a test with 4-hour
  shifts, giving the worker who'd done nothing two of three new shifts would have cut their rest well below target,
  and the best schedule split the new shifts evenly instead. That's the scoring's ordinary trade-off, for tuning
  and the audit across schedules to judge.
* The penalty reported with a history covers the whole schedule, so it isn't comparable with one without.
