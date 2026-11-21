# 0054. Rest against the schedule's typical rest, per hour of the shift before it

**Status:** Accepted (2026-11-21). Amends [ADR 0048](0048-an-audit-that-only-observes.md) (rests were compared rest by
rest against the best-off peer). Keeps [ADR 0051](0051-the-audit-after-reading-cards-by-hand.md)'s rule that a rest is
judged per hour of the shift before it.

## Context

[ADR 0053](0053-load-against-the-workers-own-share.md) took the best-off peer out of load. The user had corrected the
reasoning behind it: the audit's workers are sensitive to unfairness against themselves, not jealous of whoever got
the best deal. Rest was still compared with the best-off peer:
* each worker's rests were sorted shortest first, per hour of the shift before each, and compared in the same places
  with the peer's who gave the most events;
* one well-rested worker gave almost everyone else a grievance. On the 16 schedules read in
  [Phase 13](../roadmap.md#phase-13-a-reliable-audit)'s step 4, it gave 185 rest events, 993 hours short, with most
  workers aggrieved in most schedules;
* the [worker panel](0052-a-worker-panel-as-a-check-on-the-audit.md) never raised a rest that was short only against
  the best-rested worker.

Rest has no share, so some comparison stays. On 2026-11-12 the user had said: "if most rests are 6 h, a 6 h rest isn't
a straw"; if a schedule usually gives 12 hours, 8 hours twice is a short straw.

Measured on the same 16 schedules on 2026-11-21, with each rest per hour of the shift before it as in ADR 0051:

| way | events | hours short | events / rests, by length of the shift before |
|---|---|---|---|
| the best-off peer (before this ADR) | 185 | 993 | 1 h: 4/14 · 2 h: 157/245 · 4 h: 18/23 · 6 h: 6/6 |
| **the median of every rest** (this ADR) | 61 | 211 | 1 h: 0/14 · 2 h: 37/245 · 4 h: 18/23 · 6 h: 6/6 |
| the median per shift length, others' rests only | 62 | 130 | 1 h: 6/14 · 2 h: 47/245 · 4 h: 6/23 · 6 h: 3/6 |
| γ × the shift before (the scoring's rest factor) | 154 | 293 | 1 h: 0/14 · 2 h: 126/245 · 4 h: 22/23 · 6 h: 6/6 |

The user raised schedules whose posts have different shift lengths, which deserve different rests. A median per
shift length would hold no length to another's standard. The user proposed instead one median of rest per hour of
work, with rests before a worker's first shift and after their last excluded, so that no comparison is split by shift.

Against a single median, almost every rest after a 4- or 6-hour shift is an event, and none after a 1-hour shift. In
these schedules rests don't grow in proportion to the shift before them. But under ADR 0051's rule (a rest after a
shift twice as long has to be twice as long), a worker who gets less rest per hour of work than the rest of the
schedule is treated unfairly, even where the schedule could have done no better. As with load (ADR 0053), detection
doesn't decide what could have been avoided: the fix search does.

## Decision

1. **The schedule's typical rest** is the median of every worker's rests, each per hour of the shift before it:
   * a rest is the available time between two of a worker's consecutive shifts, as before;
   * rests before a worker's first shift and after their last aren't rests;
   * the schedule is the whole schedule, with its history if it has one.
2. **Each of a worker's rests shorter than the typical rest,** per hour of the shift before it, is an event. No peer
   is involved, and every shift length is held to the same rate.
3. **The event's size** is how much longer the rest would have to be to reach the typical rest, after a shift this
   long: (typical − rest per hour) × the shift's length. Tuning reads rest in hours short, as before. The card reads
   "N h short, after a S h shift (R h per hour of it), of the typical T h after a shift this long".
4. **The fix search is unchanged:**
   * a worker is better off in rest when no rest of theirs got shorter and one got longer (place by place, shortest
     first);
   * they are harmed when they have more rest events, or a larger one, and their own rests got worse.

   A nearby schedule has its own typical rest. A grievance that grows only because others rest longer, raising the
   typical rest, isn't harm ([ADR 0050](0050-a-fix-harms-only-where-a-workers-own-situation-gets-worse.md)).

The same rests for everyone give no event, however long or short. If most rests are 6 hours after 2-hour shifts, a
6-hour rest after a 2-hour shift is no event.

**Not taken:**
* **The best-off peer** (ADR 0048): the view of workers as jealous, given up in ADR 0053.
* **A median per shift length,** compared with others' rests only: it doesn't hold rest proportional across lengths,
  so it can't see a worker on long shifts getting less rest per hour of work than everyone else. A rest after a length
  nobody else works would go unjudged.
* **γ × the shift before** (the scoring's rest target,
  [ADR 0036](0036-rest-targets-from-the-input-convex-per-worker.md)):
  * an absolute line, which in these schedules can't be reached after long shifts: equal 6-hour rests for everyone
    would all be events, against a target of 6.9 hours;
  * the scoring's own yardstick, so tuning would reward the model for hitting its own target.
* **A line fitted through the rests by shift length:** with least squares, long overnight gaps pull it up, so most
  rests fall below it.
* **The median of each worker's rest per hour worked** (each worker's rests added up): a reading of the user's
  proposal per worker rather than per rest. It gave more events (115) for the same skew, and "shorter than the typical
  rest" is about a rest.

## Consequences

* **No grievance uses a peer any more:**
  * load is measured against the worker's share;
  * rest against the typical rest;
  * disliked partners and missing likes against the worker's own shifts.
* **Workers on long shifts often have rest events, mostly with no harmless fix:**
  * after a 4-hour shift, 18 of 23 rests were events in the measurement above, and all 6 after a 6-hour shift;
  * they will often be the most aggrieved worker in rest;
  * the reading's first measure, events with a harmless fix, keeps that from swamping tuning;
  * the re-audit of the tuning stages shows how often it happens.
* **Results audited before this ADR aren't comparable** with those after. The stored tuning stages are audited again,
  and the worker panel checks the result (Phase 13, step 4).
* **Checked by** hand-made tests:
  * the median of rests per hour;
  * a rest after a long shift judged at the same rate;
  * a rest judged by the shift before it;
  * equal rests giving no event;
  * events shortest first;
  * the closing table's rest measures, with events in the history.
