# 0045. A rest look-ahead in the lower bound

**Status:** Accepted. Amends [0024](0024-cheapest-first-value-order-and-workload-bound.md) (the lower bound's rest
part).

## Context

The lower bound's rest part ([ADR 0024](0024-cheapest-first-value-order-and-workload-bound.md)) is the rest penalty
so far, with no look-ahead. A worker can always be given no further shifts, so no single future deficit is certain:
any one unfilled slot might go to a worker who takes it with no deficit.

Some unfilled slots, though, can't avoid one: every worker still in their domain already has a shift close enough to
them that taking the slot leaves a rest short of its target. And slots too close together for one worker (they overlap,
are back to back, or are less than the minimum rest apart) must go to different workers, so such costs add up.

Measured outside the program (Phase 11 step 1, 2026-11-16; see
[Future work](../explanation/future-work.md#search-performance)): the true best completion at sampled deep nodes of
seed 3009 was above the bound by about as much in rest as in workload, and a look-ahead of this kind left 0.50–0.99
of the nodes, with 2.6 times the progress on seed 3009. On top of the exact whole-slot multiplier
([ADR 0044](0044-best-whole-slot-multiplier-by-tangents.md)), 2026-11-17: 0.51–1.00 of the nodes on inputs searched
to the end, and 2.7 and 1.7 times the progress per node on seed 3009 and `multiday_04`.

## Decision

The search adds a **rest look-ahead** to the bound, in `IncrementalScore.rest_lookahead(neighbours)`:

1. **Each unfilled slot's least increase:** $m(s)$ is the smallest increase in the rest penalty among the workers
   still in the slot's domain, if they took it now, against their current slots (`_rest_delta`, as the value order
   computes it). It's 0 as soon as one of them would take it with no increase.
2. **Why it's valid:** a worker's rest deficit never falls as slots are added to their schedule. Putting slot $s$
   between their slots $e$ and $l$ replaces the rest from $e$ to $l$ by the rests from $e$ to $s$ and from $s$ to
   $l$; the rest is split, less the time of $s$ itself (in which the worker is available), while the two targets add
   up to more than the one, so the two deficits add up to at least the one. Their term is convex and rising in the
   deficit, so it never falls either. So a worker who gets $s$, with or without other slots, ends with a rest term at
   least $m(s)$ higher than now.
3. **Groups of conflicting slots:** unfilled slots that conflict pairwise go to different workers, each adding at least
   their own $m(s)$, so the rest penalty must grow by at least the sum over any such group. (Summing $m(s)$ over every
   unfilled slot would not be valid: one worker taking two of them may pay less than the sum.)
4. **The heaviest group, from the neighbour lists:** two slots conflict exactly when one starts before the other ends
   plus the minimum rest (or touches it, with a minimum rest of 0), so conflicts behave like overlaps between
   intervals reaching from each slot's start to its end plus the minimum rest. Intervals that overlap pairwise share
   a point, and the latest-starting of them is one where they all are. So every group lies within one slot $t$
   together with the earlier slots that conflict with it, all of which conflict with each other, and the heaviest
   group is the heaviest of these: one pass over the unfilled slots with $m(s) > 0$ and their earlier neighbours.
5. **Where it's asked:** only where the incremental bound, with its whole-slot part, doesn't already prune. From
   there on, the bound means the incremental bound plus `rest_weight` times the look-ahead: it prunes if it reaches
   the pocket's penalty plus `NEAR_TIE_MARGIN`, keeps the branch if it's below the pocket's penalty less the margin,
   and near a tie it's computed from scratch ([ADR 0027](0027-incremental-scoring-for-steering.md)): `lower_bound`,
   plus the look-ahead of an `IncrementalScore` built from scratch for the current schedule. So the search decides
   the same with incremental scores or without them, node for node, as ADR 0027 requires. `lower_bound` itself, and
   `IncrementalScore.bound()`, are unchanged.

It's computed afresh at each node where it's asked: about 1.4–3.4 µs on PyPy (2026-11-17).

## Consequences

* **The same results:** the look-ahead is a valid lower bound, so it prunes only branches that can't beat the pocket.
  * Tests: on partial schedules of the small brute-force inputs, the rest so far plus the look-ahead is never above
    the rest of any completion, and it's above 0 on some of them; the search gives the same result with and without
    it.
  * On every benchmark input, alone and as day 2, on CPython and PyPy, the schedules are identical to the recorded
    ones (2026-11-17).
* **Faster where rest is what's hard, a little slower where it isn't** (2026-11-17, the program's code against
  `dev`'s; one process, four searches at a time, two rounds; a few inputs repeated two at a time):
  * PyPy, 16 inputs searched to the end: 309 s to 289 s and 302 s to 299 s in the two rounds (4–7% less), with
    0.51–1.00 of the nodes. `sweep_12` 35–37% faster; `sweep_04` about 4% and `sweep_11` about 10–13% slower
    (repeated: the look-ahead takes 8% and 12% of their time, and saves 4% and 7% of their nodes).
  * PyPy, 48-hour inputs up to 20 million nodes, progress per second: seed 3009 2.3 times, `multiday_04` 1.7–1.85,
    `multiday_05` 0.85–0.94 (no node saved).
  * CPython, 6 small inputs: 116 s to 120 s (3% more).
  * With 12 processes, the 15 benchmark inputs alone: 57 s to 51 s on PyPy, 153 s to 145 s on CPython; as day 2, with
    the first day as history: 50 s to 40 s on PyPy, 118 s to 98 s on CPython.
* **Its cost, about 4–12% of the search's time,** is paid wherever it's asked, so on inputs where no slot's rest cost is
  certain (enough workers that someone is always well rested), it's a small loss. A version kept up to date
  incrementally (which slots could add anything, changed only near each assignment) could cut that cost; it's left
  for if it's ever worth it ([Future work](../explanation/future-work.md#search-performance)). So is a quicker test
  for slots that add nothing, which saved about a quarter of the cost on some inputs and none on others.
