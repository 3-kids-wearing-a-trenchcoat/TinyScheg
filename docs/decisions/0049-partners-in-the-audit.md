# 0049. Partners in the audit: a disliked person in a shift is an event in itself; a missing like, by the worker's own likes applied to a peer's shifts

**Status:** Accepted. The like grievance is the least settled of the audit's decisions (below). Part of the audit of
[ADR 0048](0048-an-audit-that-only-observes.md), whose foundations it uses: events, the best-off peer, workers who
never net.

## Context

As built by 2026-11-19, the [schedule audit](../explanation/schedule-audit.md) treated partners like this:
* **A disliked partner:** each shift shared with anyone disliked was a short straw, added one for one to the short
  rests.
* **A liked partner:** among workers who like anyone, A complained about B if B shared shifts with someone *B* likes
  more often than A did with someone A likes, past the tolerance. Those complaints were counted apart, outside the
  summary's main measures (decided 2026-11-11), since the likes penalty can't weigh how evenly liked pairings are
  spread.

There were three problems:
* **Adding a disliked partner to a short rest is an exchange rate.**
* **Counting shifts hides people:** a shift with two disliked workers looked like one.
* **The like comparison compares the luck of two lists, not two schedules.** A worker who likes everyone has a
  friend in almost every shift, which makes everyone else aggrieved, however the shifts fell.

The user (2026-11-19): with partners, workers can be "more greedy than fair". Disliking is more urgent than liking,
and the aim is no disliked pairing at all. A like is worth about one shift sooner, about one short rest, and can't
make up for a second short rest. A 2-2-4 split "is an outrage and cannot be made up for with a liked worker"
([ADR 0039](0039-default-weights-from-the-users-trade-offs.md)).

## Decision

1. **Partners** are the workers in the other slots of the same shift, as in the [scoring](../explanation/scoring.md).
2. **Each disliked person in a shift is an event in itself,** with no peer.
   * The line is the worker's own list, not the audit's.
   * Measured against the best-off peer, it would be the same whenever anyone was spared, and would otherwise excuse a
     floor everyone shares.
   * The count is per person in a shift: not per person (5 shifts with X would look like 1), and not per shift (X
     and Y in one shift are two events, each with its own fix).
   * The size of the crew doesn't dilute it. The scoring's average over the other slots is the model's pricing, not
     the worker's experience.
   * Each side's own list counts.
3. **A missing like is only a grievance against a peer,** judged by the worker's **own** likes applied to the peer's
   shifts: "your shifts would have put me with someone I like more often than mine did" (the envy-free test).
   * It isn't each worker's satisfaction with their own list, which would compare the luck of two lists.
   * It's counted per liked person per shift, the partners in the peer's shift being its other workers apart from
     both. Each event is one of the peer's shifts the worker can point to.
   * The best-off peer is the one giving the most events.
4. **Every worker can be the peer.**
   * The peer's count is scaled to the worker's number of shifts, down only, and only whole pairings count. Comparing
     a peer with fewer shifts as they are never invents a grievance over a boon, so unlike for load, such peers stay
     peers, and the worker with the most shifts is measured.
   * A worker who likes nobody has no like grievance.
   * Levelling down remains (taking a friend from the peer removes the grievance), as with rest. A fix doesn't count
     it ([ADR 0048](0048-an-audit-that-only-observes.md): the worker must be better off).
5. **The liked pairings each worker got are a fact on the card, not a grievance:** the greedy side, a boon. Tuning
   reads them as a total, and worker by worker.
6. **The reading never nets.** On the tuning page:
   * kinds are never added together;
   * ADR 0039's rules apply: likes are weighed last, and a like stands against at most one rest event of the same
     worker, never against load.

   This answers the user's worry that liked pairings could be used as an excuse to load a worker.

### Less settled

The user wasn't entirely convinced likes should be compared against peers at all. The peer-free versions each fail:
* **Every shift without anyone they like** mostly measures the input. The worker with the rarest friend is always
  the most aggrieved, and only fewer shifts helps.
* **A liked person on duty at the same time, at another post,** never fires with one post, and rewards keeping
  friends apart in time.
* **"Never once with X"** is silenced by a single pairing.
* **A pairing a harmless change could add** makes the grievance depend on the fix search, which was ruled out from
  the start.

The alternative kept for a revisit is **no like grievance at all**, only the boon count. Then no easy fixes are
sought for likes, and the reading is left to judge who got the friends. A revisit supersedes this ADR alone.

## Consequences

* **A shift with two disliked workers is two events,** each with its own fix. A worker's disliked pairings are seen
  even when everyone has some.
* **A worker who likes many people no longer makes others aggrieved:** each worker's likes are judged on the peers'
  shifts.
* **Liked partners are no longer counted apart.** Like every kind, they're listed and compared on their own,
  and weighing them is the reading's job. The doubt of 2026-11-11, whether workers hold the spread of liked pairings
  against a schedule, moves to the reading, and to this ADR's less settled part.
* **The rest events show who was in the shifts around them** ([ADR 0048](0048-an-audit-that-only-observes.md)), so
  that a short rest into a shift with a friend can be seen.
