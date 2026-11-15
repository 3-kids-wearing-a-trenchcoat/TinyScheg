# 0036. Rest targets derived from the input, for the rest between two shifts, with each worker's shortfall squared

**Status:** Accepted. Supersedes [ADR 0028](0028-rest-factor-default-2-5.md); amends
[0014](0014-exact-worst-rest-deficit.md) (each step's target). Amended by [0038](0038-rests-count-only-available-time.md)
(rests are counted in available time).

## Context

The rest part gave each rest after a shift $s$ a target of $\gamma \cdot |s|$, with the rest factor $\gamma$ a
parameter (2.5 by default, ADR 0028), and added up each worker's hours below target, normalized by their worst
possible total ([ADR 0014](0014-exact-worst-rest-deficit.md), [ADR 0032](0032-flat-penalty-parts.md)). Found on
2026-11-13, independently of the [audit](../explanation/schedule-audit.md):

* **It's silent after short shifts.** A target at or below the minimum rest $m$ can never be missed, so with
  $\gamma = 2.5$ and $m = 6$, every rest after a shift of 2.4 hours or less costs nothing, and cramming a worker at
  the minimum is as good as spreading their shifts out. In the user's real schedules most shifts are 2–3 hours long,
  next to some much longer ones; no single $\gamma$ suits both.
* **It doesn't adapt.** In a loose schedule, where long rests are the norm, a rest well short of the norm but above
  $\gamma \cdot |s|$ costs nothing.
* **It's linear across workers.** The same total shortfall costs the same whether it's spread or all on one worker,
  so there's no "making it up" to a worker for rest, as there is for workload.

The user (2026-11-13 and 2026-11-14): the minimum rest is the hard constraint, set to what the scheduler believes is
mandatory; maximizing rest beyond it is the soft one. No value should be set by hand (they doubt one could be right
for every scenario). TinyScheg is to be task-agnostic: a reserve-duty schedule of 2–3-hour shifts, an office with
long ones, a mission with very short ones. Workers expect to be made up to over time. An "average shift", for
estimating how many shifts a worker will get, "feels off" when one post is unlike the others (an 8-hour patrol, or
being on call, among 3-hour posts).

Prototypes measured on 2026-11-13 and 2026-11-14 (the example and the 15 benchmark inputs, alone and as day 2 of a
two-day schedule; archived outside the repository):

* A cost for every rest, $|s| / (|s| + \text{rest})$, with no target, has the right properties but leaves too much
  of the penalty unseen by pruning: 7 of the 15 inputs didn't finish in 30 minutes, even with a look-ahead.
* A target of $\gamma \cdot |s|$ with $\gamma$ derived from the input (below) cut the rests under 8 hours by about
  40% and kept the search fast on 14 inputs, but on `confirm_01` it rested five workers 10–14 hours and crammed one at
  the minimum, the linear sum making that cheaper than spreading the shortfall, and took 9 times today's nodes
  there.
* Squaring each worker's shortfall undid that, and brought the search back to within 1.3 times today's nodes
  (30.2 M against 23.7 M in all; `confirm_01` 131 s against 50 s).

## Decision

1. **The rest factor is derived from the input:**
   $\gamma = \big(\sum_w \text{av}_w - H\big) / H$, the schedule's free hours per hour of work, where
   $\text{av}_w$ is worker $w$'s available hours and $H$ the total hours of all slots, over the whole schedule
   (history included, as everything else, [ADR 0031](0031-history-as-the-filled-part-of-one-schedule.md)). Since fair
   shares of work are proportional to availability (the workload part), it's every worker's free time over their
   fair share: a worker who works their share, spread evenly, gets exactly their share of free time after each hour
   of work. No count of shifts is estimated, and nothing is set by hand.
2. **The target is for the rest between two consecutive shifts** $s$ and $s'$ of a worker:
   $\gamma \cdot (|s| + |s'|) / 2$. Each shift sits in the middle of its share of free time, half before it and half
   after, so the same two shifts cost the same in either order, and nothing is assumed about which side of a shift its
   demand falls on (a patrol is tiring after; being on call may not be). The rest before a worker's first shift and
   after their last aren't judged, as before.
3. **Each worker's shortfall is squared.** With $D_w$ their hours below target in all, their term is
   $\frac{\bar M}{M_w} \cdot \frac{D_w^2}{\tau}$, where $M_w$ is their worst possible $D_w$ and $\bar M$ the mean
   $M_w$, as before, and $\tau = \gamma \cdot \bar{|s|}$, one typical target ($\bar{|s|}$ the mean slot length),
   derived from the input too. The same shortfall costs more on a worker who already has some, the history
   included, so it's spread rather than concentrated. Measured in typical targets, the square doesn't depend on the
   unit of time, and at half a typical target short an hour costs what it did before.
4. **The `rest_factor` parameter is removed.** An input that still sets it is rejected, with a message saying the
   rest targets are now derived from the input.

Both totals only grow as slots are filled (a new shift splits a rest into two whose targets add up to the old one's
plus one more shift's), so the penalty stays monotone, and the search's bounds and incremental scoring work as before;
the incremental score keeps each worker's shortfall.

The rest part is checked by **provable properties**, as tests on small hand-built schedules in which only rest
differs: with 2- and 3-hour shifts, resting well beats resting at the minimum; with a minimum rest of 0, even rests
beat crammed ones; in a loose schedule, resting as long as the norm beats resting well short of it; with a 2-hour and
an 8-hour post together, neither is silent and a long shift earns its rest; the same pair costs the same in either
order; the same shortfall on two workers beats it on one; an office-like schedule (8-hour shifts round the clock)
and a very short one (30-minute shifts, minimum rest 0) behave the same way; and a worker idle in the history makes up
for it. The previous rest part failed six of these.

## Consequences

* On the benchmark (alone / day 2): rests under 8 hours 57% / 43% before, 49% / 33% after; the spread of workers'
  shortest rests 77 / 61 before, 76 / 55 after; the gaps in hours and shift counts between fully available peers
  about the same alone and smaller on day 2 (largest hours gap 10 before, 7 after).
* Squaring makes small shortfalls cheaper than before (under half a typical target) and large ones dearer, so the
  balance between the rest part and the others has moved; the weights are to be checked again.
* Where spreading the average worker's share evenly gives no more than the minimum rest (`sweep_02`, where
  $\gamma \cdot |s|$ is exactly 6 hours for its 2-hour shifts), the targets sit at the minimum and the rest part
  stays silent there. A worker who gets fewer shifts than their share then has room the target doesn't see.
* The worst possible shortfall $M_w$ is computed over the slots each worker could fill, which, with a history,
  doesn't include history slots someone else worked; that, and rests that contain unavailable time, are the next
  steps on the roadmap.
* Inputs that set `rest_factor` must drop it.
