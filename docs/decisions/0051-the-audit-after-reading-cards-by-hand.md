# 0051. The audit after reading cards by hand: load in hours, rest by the shift just done, a missing like in the worker's own shifts, a dislike cancels the like it meets

**Status:** Accepted. Amends [ADR 0048](0048-an-audit-that-only-observes.md) (load is measured in hours alone; a rest
is judged by the shift before it) and [ADR 0049](0049-partners-in-the-audit.md) (a missing like is a shift with
nobody the worker likes, with no peer; a like for someone who dislikes the worker doesn't count).

## Context

In [Phase 13](../explanation/schedule-audit.md)'s step 4 (validation), the user read eight cards by hand on
2026-11-20. Each was shown on the schedule as TinyScheg writes it, with the worker's grievances, their fixes and each
fix's effect on every worker. Four of the user's answers disagree with the audit of ADRs 0048 and 0049:

* **Load.** Avery's two 2-hour shifts counted as an extra shift against Blake's one 4-hour shift. The user: "I do
  not believe this should be counted as having an extra shift over Blake ... we should measure hours rather than
  'number of shifts'." ADR 0048 measured shifts and hours, more by one and no less by the other, from the user's
  answer of 2026-11-12, "both, in some proportion"
  ([ADR 0026](0026-workload-counts-shifts-and-hours.md)). On 2026-11-14 the user had said hours alone ("there's no
  reason to explicitly count the shifts").
* **Missing likes.** Emery missed a pairing with Harper because a peer had Harper in more shifts. Gray missed one with
  Casey because Harper had shifts with Casey. The user: "Workers would complain about not being assigned with
  someone they like, but they wouldn't complain about someone they like being assigned with someone else." Gray's
  complaint "should be being assigned with someone other than who they like". On another card, Emery and Kai like
  each other, and Emery's third shift was with Blake: the user expected Emery to complain about that shift, which the
  audit didn't list, since no peer had Kai in more shifts than Emery.
* **One-sided likes.** Casey dislikes Gray, who likes Casey. The user: the dislike "should supersede Gray liking
  Casey". The user also floated making likes and dislikes symmetric, leaving it to whoever writes the input to decide
  how to read one-sided feelings.
* **Rest.** Avery's 10 hours between a 2-hour and a 4-hour shift counted as 2 hours short of Emery's 8 hours between
  two 2-hour shifts, since rests were compared per hour of the mean of the two shifts around them (3.3 against 4).
  The user: "it's expected for the rest after a shift that's twice as long to also be twice as long, and I don't
  think other workers should complain about another worker getting a 'longer rest' if this longer rest is
  proportional to the shift they just did." Asked to choose between judging a rest by both shifts around it, by the
  shift before it, or as shorter only if shorter both in hours and per hour, the user chose the shift before it.

The user also said, on 2026-11-20, that grievances are expected: "we're not aiming for a grievance-free schedule ...
there will always be some grievances, that's okay." The other answers needed no change: events wholly in the history
stay on the cards, and every fix stays listed, below the grievances.

## Decision

### 1. Load is measured in hours alone

1. **A worker did more than a peer if they worked more hours** than the peer's hours, scaled down to the worker's
   availability (as before: peers available at least as long, scaled down only). The number of shifts doesn't count.
2. **Each event is still a shift the worker can point to:** as many of their own shifts, shortest first, as fit in
   the extra hours. With shifts of one length, that's the whole extra shifts. Extra hours shorter than the worker's
   shortest shift are no event.
3. **The extra hours are the grievance's size,** a fact on it. Tuning records load in extra hours too, like rest in
   hours short: for the events with a harmless fix, for the most aggrieved worker, and in all.
4. **The best-off peer** is the one giving the most events, then the most extra hours (the strongest case), then the
   first in input order. Avery's card named Blake, at no extra hours, only because Blake came first among peers
   giving one event each.
5. **In the fix search** ([ADR 0048](0048-an-audit-that-only-observes.md), [ADR 0050](0050-a-fix-harms-only-where-a-workers-own-situation-gets-worse.md)),
   a worker is better off in load with fewer hours, and worse off with more.

The model still counts shifts, through the shift share ([ADR 0026](0026-workload-counts-shifts-and-hours.md), 0.5 by
default). Whether it should stop is a tuning question for later, which the audit can now answer; this ADR doesn't
change the model.

### 2. A rest is judged by the shift just done

1. **A rest is measured per hour of the shift before it:** its available part
   ([ADR 0038](0038-rests-count-only-available-time.md)) divided by that shift's length. A rest after a shift twice
   as long has to be twice as long to be as good.
2. **Everything else stays** ([ADR 0048](0048-an-audit-that-only-observes.md)): rests compared rest by rest against
   the best-off peer, both sorted shortest first (per hour of the shift before each), every worker a peer. The size
   is how much longer the rest would have to be to match the peer's, after a shift this long.
3. **In the fix search,** rests are compared the same way.

The model's rest target ([ADR 0036](0036-rest-targets-from-the-input-convex-per-worker.md)) still uses the mean of the
two shifts around a rest, so the audit now judges rest slightly differently from what the model aims at. Whether the
target should follow is a question for later.

### 3. A missing like is a shift with nobody the worker likes

1. **Each of a worker's shifts that has partners, none of whom they like, is an event,** with no peer. Partners are
   the workers in the other slots of the same shift, as before.
2. **A shift worked alone isn't an event:** there's nobody the worker could have been with. A worker who likes nobody
   (after point 4) has no like grievance.
3. **In the fix search,** a worker is better off with fewer such shifts, and worse off with more. One grievance per
   worker, so a fix is judged on all of their shifts at once.
4. **Their liked pairings** (each liked person in each of their shifts) stay a fact on their card, the boon.

ADR 0049 turned down "every shift without anyone they like" because it mostly measures the input: the worker whose
friend is rarely on duty always has the most events. That matters less now:
* the user expects grievances;
* tuning compares settings on the same inputs, so whatever an input forces is the same on both sides;
* the reading's first measure, the events with a harmless fix, picks out the ones that could have been avoided.

### 4. A dislike cancels the like it meets

1. **Where B dislikes A, A's like for B doesn't count** in the audit: not for A's missing likes, nor for A's liked
   pairings. B's disliked-partner events stay.
2. The scoring already treats such a pair as costing more than it gains
   ([ADR 0023](0023-dislikes-outweigh-likes.md)): pairing them is never what a worker could rightly ask for.

**Symmetric preferences,** one relation per pair decided by whoever writes the input, would settle this too. They
would change the input format, the scoring and every benchmark input, a change to the model rather than to the audit.
They're left for later.

**Not taken:**
* **Load in shifts and hours** (ADR 0048): two short shifts against one long one, at the same hours, isn't more load.
* **A rest judged by the mean of both shifts around it** (ADR 0048): a rest longer in hours counts as short because
  of the shift after it.
* **A rest short only if shorter both in hours and per hour:** a longer shift followed by an equally long rest would
  never be short, against "twice as long".
* **A missing like judged on the peer's shifts** (ADR 0049's envy test): workers don't hold a friend's shifts with
  someone else against the schedule.

## Consequences

* **On the 16 schedules read by hand** (the defaults' next-period stage, first periods and both periods; grievances
  only, before the fix search):
  * load events go from 104 to 86: 27 disappear (more shifts at the same hours) and 9 appear (more hours in fewer
    shifts, which counted as neither more nor less);
  * missing-like events go from 131, for 68 workers, to 67, for 48;
  * 22 likes are cancelled by a dislike.
* **On the cards read:**
  * Casey's harmless fix (`sweep_09`) gave Gray 2 more hours. Measured in hours, that's a load event for Gray, so the
    fix is a transfer, as the user hesitated to call it harmless. (With rests judged by the shift before them,
    Casey's rest is now measured against Avery's 6 hours after a 1-hour shift, and has only transfers.)
  * Avery's load event remains, against Drew (4 hours against 2), not Blake.
  * Avery's rest event (`sweep_11`, both periods) disappears: 10 hours after a 2-hour shift is 5 hours per hour of
    it, against Emery's 4.
  * Gray has no grievance left: Gray's only like is for Casey, who dislikes Gray.
  * Emery's shift with Blake (`sweep_02`) is a missing like.
* **Results audited before this ADR aren't comparable** with those after. The stored tuning stages are audited
  again, and step 4's checks repeated.
* **Left for later** (the roadmap's "Later" section and
  [future work](../explanation/future-work.md)): symmetric preferences; whether the model's shift share should go to
  0; whether the model's rest target should follow the shift before a rest.
* **Checked by** a hand-made test for each decision, the fix search against brute force on small inputs, and cards
  read by hand again.
