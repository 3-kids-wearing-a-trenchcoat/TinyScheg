# 0053. Load against the worker's own share, its events rounded to the nearest shift

**Status:** Accepted (2026-11-21). Amends [ADR 0048](0048-an-audit-that-only-observes.md) (load was measured against
the best-off peer, among peers available at least as long, scaled down to the worker's availability) and
[ADR 0051](0051-the-audit-after-reading-cards-by-hand.md) (a load event was a shift of the worker's that fitted in the
extra hours).

## Context

The [worker panel](0052-a-worker-panel-as-a-check-on-the-audit.md)'s first run, on the 174 workers of the 16
schedules read in [Phase 13](../roadmap.md#phase-13-a-reliable-audit)'s step 4, disagreed with the audit on load in
two ways:

* **22 load complaints the audit didn't have.** In 19 of them, the worker's extra hours were fewer than their
  shortest shift, which under ADR 0051 is no event. In one case, a worker did one 6-hour shift while peers did
  3 hours: twice their load, and no event. In another, a worker did 4 hours in 2-hour shifts against peers' 3 hours.
  The rule left avoidability to detection: if no transfer of one of the worker's shifts would shrink the gap, nothing
  was recorded, not even the hours. Avoidability is the fix search's job.
* **15 load grievances no worker raised.** These workers were at their even share, but above the best-off peer. In
  one schedule, seven workers at their share of 10 hours each had a grievance against a worker on 8, while the hours
  that worker didn't do had fallen on two workers on 12 and 14.

On 2026-11-21 the user approved rounding a worker's extra hours to the nearest shift. Discussing the second point, the
user corrected the reasoning behind the best-off peer, which leaned on two views since given up:
* workers as "self-centred and jealous" (2026-11-12): the audit's workers are **sensitive to unfairness against
  themselves** ([ADR 0048](0048-an-audit-that-only-observes.md), 1.5);
* evenness overriding the total: the user walked that back on 2026-11-19, and the tuning reading takes evenness as one
  input among others.

A worker who is sensitive to fairness objects when they are treated unfairly. For load, the project's rule for what's
fair is a share in proportion to availability ([ADR 0013](0013-availability-weighted-workload.md)). A worker at their
share carries no one else's work, however little someone else did.

## Decision

1. **A worker's load grievance is the hours they worked above their own share:**
   * the share is the schedule's hours split in proportion to availability: the hours worked by everyone, times the
     worker's availability over everyone's;
   * availability is counted only when a post is staffed, as before;
   * the schedule is the whole schedule, with its history if it has one.

   No peer is involved. So the rules about which peers count (only those available at least as long, their hours
   scaled down to the worker's availability, never up) fall away: the share already scales by availability.
2. **Events are the worker's own shifts, shortest first, rounded to the nearest shift.** Each shift counts when at
   least half of it falls within what's left of the extra hours (the constant `LOAD_EVENT_SHARE`, 0.5):
   * one 6-hour shift against a share of 3 hours is 1 event;
   * 4 hours in 2-hour shifts against a share of 3.6 hours is none;
   * 5 extra hours in 2-hour shifts are 3 events.

   Each event is still a shift the worker can point to.
3. **The extra hours are the grievance's size.** Tuning records them as before. The card reads "N h more than X's
   share of S h".
4. **The fix search is unchanged:** a worker is better off in load with fewer hours, and worse off with more. A
   nearby schedule has the same slots and the same availability, so the share is the same in every one of them.
5. **Whether an event could have been avoided stays with the fix search.** A 6-hour shift moved to a worker with fewer
   hours than their share is a transfer if it gives them a load event, and harmless otherwise.

**Not taken:**
* **A shift counted only if it fits in the extra hours** (ADR 0051): large but lumpy imbalances recorded nothing.
* **Any extra hours as a grievance with no events:** it would need a cut-off below which a difference is noise, a new
  setting.
* **The best-off peer** (ADR 0048): a worker at their share isn't treated unfairly in load because someone else did
  less. One light worker gave everyone above them a grievance.
* **Above the share and above the best-off peer, sized against the peer:** it keeps the peer only to size the
  grievance, and the peer's hours overstate what the worker carried for others.

## Consequences

* **Rest is still judged against the best-off peer.** Rest has no share, so some comparison with others stays. Whether
  it should be with a typical rest in the schedule rather than the best one comes from the same correction. It is
  discussed next, in Phase 13's step 4 (settled in [ADR 0054](0054-rest-against-the-typical-rest.md)).
* **Results audited before this ADR aren't comparable** with those after. The stored tuning stages are audited again
  once the rest question is settled, and the worker panel checks the result.
* **Checked by** hand-made tests: a 2-2-3 split; a worker at their share beside a light worker; shares by
  availability, with and without a history; a single long shift half of which is extra; extra hours counted shortest
  first.
