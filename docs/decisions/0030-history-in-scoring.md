# 0030. History in scoring: the history and the new schedule scored as one

**Status:** Accepted. Amended by [0031](0031-history-as-the-filled-part-of-one-schedule.md) (points 1–3: scored
as one schedule from scratch, with no special cases).

## Context

With previous schedules read back as fixed history ([ADR 0029](0029-schedule-history-input.md)), the scoring has to
decide how the history affects the new schedule. Workers expect to be "made up to" when they drew more than others
and there was no way round it, and judge fairness relative to their availability: being away isn't a debt. The model
should carry this in its mathematics, with the [schedule audit](../explanation/schedule-audit.md) checking it
explicitly (decided with the user, 2026-11-12).

## Decision

**The history and the new schedule are scored as one longer schedule, with the history's assignments fixed.** Only
the parts that the new schedule's choices can change are counted; everything else would be a constant, which can't
change which schedule is best.

1. **Workload** counts each worker's load and availability over the history and the new period together:
   $h(w_i) = (L^\text{hist}_i + L_i) / (\mathrm{av}^\text{hist}_i + \mathrm{av}_i)$. A worker who carried more
   before now has a higher workload to start from, and the convex penalty steers new load to the others: being made
   up to follows from the existing formula, with no new term.
   * **Availability in the history** comes from each history input: its period minus the worker's unavailability in
     it. A worker who wasn't in a history input (they joined later) was unavailable then: they neither owe nor are
     owed anything for it.
   * **Each history shift's load** is computed as in its own schedule, $\ell(s) = (1 - \sigma)|s| + \sigma \bar{L}$
     with $\bar{L}$ the mean slot length **of that schedule** (each schedule sets its own norm), and the current
     shift share $\sigma$.
   * **The normalization stays the new period's own** ($\sum_i \mathrm{av}_i \varphi(h^{\max}_i)$ over the new
     period, as now). The marginal cost of giving a worker more load depends on their workload, not on how much
     history there is, while a denominator over history and new period together would grow with every schedule
     added and shrink the workload term against likes and rest, against the tuned weights. So with history the
     normalized workload can exceed $k$; only its differences matter.
2. **Rest** counts, in addition to the new period's rests, the rest between each worker's **last history shift** and
   their first new one, with the same deficit $\max(0, \gamma |s| - \text{rest})$. Rests within the history are fixed
   and left out. The worker's worst deficit $M_w$ counts that last history shift among their possible shifts.
3. **Likes** count only the new schedule's pairings: the history's are fixed.
4. **The search is unchanged.** The history is a fixed starting point, so the penalty is still monotone along the
   search; the workload look-ahead starts from each worker's history load; incremental scoring starts from the same
   totals.

How far back fairness reaches is set by which previous schedules the input lists.

Rejected:

* **Older history weighted less** (a decay parameter): it would stop long histories from outweighing the present,
  but it's a new parameter and formula. To be reconsidered if listing only recent schedules isn't enough.
* **Only the minimum rest at the boundary**, with no fairness carried over: simplest, but imbalances would still
  accumulate, which is the problem to solve.
* **Normalizing over the history and the new period together**: see 1.

## Consequences

* **Past short straws aren't compensated.** A disliked pairing or a short rest in the history is a constant in the
  penalty, and neither the likes nor the rest penalty weighs one worker's straws against another's, so the model
  gives no one "their turn" for them. Load is compensated; straws aren't. The audit across schedules is to show
  whether that matters; if it does, it needs a per-worker term, with its own ADR.
* A schedule's penalty with history isn't comparable with its penalty without, nor across different histories.
* The [tuning](../explanation/tuning.md) was done without history; whether the defaults still work with it is for the
  audit across schedules to check.
