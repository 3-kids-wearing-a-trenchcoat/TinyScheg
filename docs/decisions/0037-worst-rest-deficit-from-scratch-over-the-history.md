# 0037. Each worker's worst rest deficit counts every history slot they could have filled

**Status:** Accepted. Refines how [ADR 0031](0031-history-as-the-filled-part-of-one-schedule.md)'s point 4 (the
constants computed over the whole schedule) applies to the worst rest deficit.

## Context

A worker's hours short are divided by their worst possible deficit $M_w$, the largest total any legal sequence of
the slots they could fill would give ([ADR 0014](0014-exact-worst-rest-deficit.md)), so that an hour short weighs
more for a worker whose availability allows only a mild worst case
([Scoring](../explanation/scoring.md#scaling-the-rest-deficit)). With a history, the slots a worker "could fill" were
read from the search's domains, where a history slot has only the worker who worked it. So $M_w$ grew with the
history slots a worker had been given, and a worker passed over in the history had a smaller one, making their
hours short dearer than everyone else's.

Found on 2026-11-14, with the history test that the new schedule makes up for it: Anne and Bob took turns over 12
hours of 2-hour shifts at the minimum rest, Cy did nothing. With the rest factor of 2.5 then, Cy's worst case was 6
hours against Anne's and Bob's 15,
so an hour short cost Cy 2.5 times as much, and the best next 12 hours split the shifts evenly instead of giving Cy
more. Computed as if Cy could have worked the history slots, as in a schedule made from scratch, the best schedule
gave Cy three of the six. The test had passed only because it silenced the rest part. On the benchmark's day 2,
workers' worst cases were up to several times smaller than from scratch, the least so for those who had worked
most on day 1.

The user (2026-11-14): unavailability (sickness, leave, a one-off duty) is neither work nor rest, and no reason for
it is to be rewarded or penalized; a worker available for 24 hours with 2 shifts and one available for 12 with 1
have the same workload. The history's unavailability must be kept, not lost. ADR 0031's principle is that a schedule
with a history is treated as the middle of one made from scratch.

## Decision

**A history slot counts in the worst rest deficit of every worker who could have filled it in its own period:**
who was in that period's input, available for the slot's whole time as that input gave it, and with the slot's role
as that input gave it, not only the worker who did. A new slot counts for the workers of its initial domain, as
without a history. Being passed over no longer changes a worker's worst case; being unavailable still does, as
the workload part counts only available time.

The problem keeps, for each slot, the workers who could have filled it from scratch (`Problem.eligible`, read
through `scoring_domains`, the same as the search's domains without a history), and the scoring constants are built
from it. The search's own domains are unchanged.

## Consequences

* The history test makes up for the history without relying on the squared rest part
  ([ADR 0036](0036-rest-targets-from-the-input-convex-per-worker.md)) alone; tests check who counts for a history
  slot (availability and roles of its own period, workers who joined later) and that an idle worker's worst case is
  the same as their peers'.
* Without a history nothing changes. On the benchmark's day 2, 8 of the 9 schedules are the same; the other has the
  same measures, with one audit complaint more. Day-1 schedules there share the work fairly, so the skew rarely
  decided anything.
* Every caller of `build_constants` passes `problem.scoring_domains`, the development tools included.
