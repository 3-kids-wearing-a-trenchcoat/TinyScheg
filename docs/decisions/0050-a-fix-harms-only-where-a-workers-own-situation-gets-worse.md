# 0050. A fix harms a worker only where their own situation gets worse

**Status:** Accepted. Amends [ADR 0048](0048-an-audit-that-only-observes.md) (what a fix creates, and so which fixes
are harmless).

## Context

In [ADR 0048](0048-an-audit-that-only-observes.md), a fix is harmless if no worker has more events of any kind, or a
rest event larger when sorted by size, than in the audited schedule. Otherwise it's a transfer, reported with what it
creates.

Grievances are measured against the best-off peer. Building the report (Phase 13, step 3, 2026-11-20), the transfers
found on real schedules turned out to "create" mostly grievances for bystanders whose own schedules hadn't changed:
* **Seed 150 of the example: Jeff has an extra shift.** Whoever takes it, every fix also gave Jack, Anne, Gilgamesh
  and Siduri a larger rest event. The shift Jeff gives away sat between two of his rests, which become one long rest,
  so Jeff becomes the best-rested worker and everyone's shortfall against him grows.
* **`confirm_01`: Casey has an extra shift.** Every fix also gave Avery, Indy and Kai a missed like with Harper. With
  fewer shifts, Casey's pairings with Harper count for more once scaled.

So a single move "created" 5 to 9 grievances, almost nothing was harmless, and every different mix of bystanders made
another undominated transfer. A complete search up to 3 changes, on 50 samples of the example and the 75 stored tuning
schedules:
* **As decided in ADR 0048:** 54% and 1% of grievances had a harmless fix, and grievances with only transfers had a
  median of 19 and 66 of them (up to thousands in a schedule).
* **Counting only what makes a worker worse off in their own situation** (more work, a shorter rest, ...) is wrong
  the other way: any move gives the receiver more work, so even a shift given to the worker with the fewest would
  harm them. Load and rest are fair or unfair only against others. 1% and 0% had a harmless fix.

The user chose the rule between the two (2026-11-20).

## Decision

1. **A worker is harmed by a fix only where, in one kind, they have more events (or a larger rest event) and their own
   situation in that kind got worse:**
   * load: more shifts or more hours;
   * rest: more rests than before, or a rest shorter than the one in its place before (both sorted shortest first, per
     hour of the shifts around them). A worker who gains a rest (a second shift) and a rest grievance with it is
     harmed;
   * disliked partner: more shifts with that person;
   * missing like: fewer shifts with that person.
2. **A fix creates only those, and is harmless if it creates nothing.** A grievance that grows only because someone
   else is better off (a new best-off peer) isn't created by the fix.
3. **Unchanged:** the worker being fixed must be better off in that kind, so levelling down is still no fix; and the
   grievances of the audited schedule are found as before.

Example: in a 3-2-1 split, giving one of the first worker's shifts to the third leaves 2-2-2. The third worker works
more, but has no new grievance, so they aren't harmed, and the fix is harmless. If the extra shift went to the second
worker instead (2-3-1), that worker would have more shifts and a new load event: harmed, a transfer.

## Consequences

* **More harmless fixes, and readable transfers.** Under this rule, the same complete search gives 81% of grievances a
  harmless fix on the example and 4% on the tuning schedules, which are close to the best the model finds. Grievances
  with only transfers have a median of 6 and 17 of them (at most 12 and 93). A transfer reads as a scheduler's
  option: "give Jack's 13:00 to Enkidu: Enkidu, 1 extra shift". Whether listing them all on the card is too long is
  judged when reading cards (Phase 13, step 4).
* **What it gives up:** after a harmless fix, bystanders can be further behind the best-off peer. In the example, after
  Jeff's shift goes elsewhere, Jeff rests best and the others fall further short of him. Auditing the nearby schedule
  shows it; the fix doesn't count it as harm, since nothing in their own schedules changed.
* **Cost:** a median of 2.5 seconds per sample of the example (at most 10) and 13 seconds per tuning schedule (at most
  92, on a 48-hour one).
* **Tested:** a grievance grown only because a peer is better off isn't created; a shift given to a worker who had
  fewer harms nobody; a larger rest event with a shorter rest is created; the search still matches brute force.
* **The search needs no shortcut** (ADR 0048 allowed one, at least one change touching the grievance's workers): each
  nearby schedule is audited once and checked against every grievance.
