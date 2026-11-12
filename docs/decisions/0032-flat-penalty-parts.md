# 0032. Flat penalty parts: one event costs the same at any schedule length

**Status:** Accepted. Supersedes [0015](0015-normalize-workload-by-packable-maximum.md); amends
[0005](0005-weighted-sum-of-normalized-penalties.md) (the parts are no longer normalized to $[0, k]$) and
[0022](0022-scoring-parameters-with-defaults-and-input-overrides.md) (the default weights).

## Context

Each part of the penalty was divided by the most it could be in the schedule: likes by $\beta \cdot n_\text{shared}$
(correction 4 of the [2026-11-10 review](../explanation/scoring.md#corrections)), workload by the sum of each
worker's packable maximum ([ADR 0015](0015-normalize-workload-by-packable-maximum.md)), and rest by each worker's
worst possible deficit $M_w$. Those maxima grow with the schedule's length, each at its own rate, so what one
concrete event costs drifted with length, and not in step. Measured on 2026-11-12 on the example and 8 tuning
inputs, from half to four times their length:

* a disliked pairing and an hour of short rest cost about 1/length;
* a one-shift imbalance cost about 1/length²: a shift is a smaller share of a longer availability, and the divisor
  grows with availability too.

On the 96-hour example a two-shift gap was then worth about a fifth of a disliked pairing, against about two-thirds
at 24 hours. Every schedule with a history is longer than one without
([ADR 0031](0031-history-as-the-filled-part-of-one-schedule.md)), so the trade-off tuned on 16–24-hour schedules
didn't hold where history is used.

The user's view of the scoring (2026-11-12): penalties only matter when comparing solutions, so a penalty every
option carries is neutral, and a total that grows with the schedule doesn't matter; the weights are just what each
part is multiplied by. The original design had likes flat, as $\mathcal{L}^*/\beta$; the reason given for changing
it (that the weights' meaning depended on the schedule's size) doesn't hold under that view.

## Decision

**Each part is measured in fixed units, so that one event costs the same at any schedule length.**

1. **Likes:** $\mathcal{L}^{**} = \mathcal{L}^*/\beta$, the original design: the sum of like values, in units of a
   disliked partner.
2. **Workload:** $\mathcal{W}^* = \sum_i \mathrm{av}_i \, \varphi(h_i) \,/\, u_W$, with the **workload unit**
   $u_W = \bar{\ell}^{\,p} / \overline{\mathrm{av}}^{\,p-1}$: an average worker's term for one average slot
   ($\bar{\ell}$ the mean slot load, $\overline{\mathrm{av}}$ the mean availability of the workers with any).
   Moving one average slot between two average workers with the same load then costs 2 units, at any length. The
   packable maximum $H^{\max}$ is no longer needed.
3. **Rest:** $\mathcal{R}^{**} = \bar{M} \sum_w \mathcal{R}_t(w) / M_w$, with $\bar{M}$ the mean worst deficit of the
   workers who could have one. Dividing by each worker's own $M_w$ is kept, the user's design: an hour short weighs
   more for a worker who could rarely be short. Multiplying by $\bar{M}$ keeps the average hour costing the same at
   any length.
4. **Default weights** are set so that, on the tuning inputs, the three kinds of event trade against each other as
   they did before: likes 0.57, workload 0.215, rest 0.215 (from 0.25, 0.5, 0.25). Before, the medians over the 8
   tuning inputs were about 0.11 for a disliked pairing instead of a neutral one, 0.13 for a two-shift gap and 0.06
   for an hour short; the new weights keep those proportions (the costs themselves are all about 3.4 times larger,
   which changes no comparison).

Each unit is a constant computed once before the search, so every part stays monotone, path-independent and
minimal exactly where it was; the search, its bounds and incremental scoring change only in the constants they
divide or multiply by.

Rejected:

* **Fixed units for rest too** (every hour short the same for everyone): tested, no better, and it drops the
  per-worker fairness the user designed.
* **Rescaling workload only**, so that it falls like 1/length as the others did: roughly holds the trade-off, but
  keeps the drift of all three parts and the maxima that cause it.
* **Keeping the maxima and recording the drift as a known limit**: the trade-off on long schedules, and on every
  schedule with history, would stay one that was never tuned.

## Consequences

* Tested on 2026-11-12 on every benchmark input, alone and as day 2 of two consecutive schedules, both audited:
  alone, the audit was the same as before on all 15 inputs; on day 2, the same on 7 of 10, worse on 3. One of
  those is a tie the model can't tell apart (every easy fix there changes the penalty by exactly 0, before and
  after), and two are rest-against-load trade-offs that the old penalty discounted on 48-hour schedules and the
  flat one doesn't. Search time alone was about the same in total (608 s against 624 s), faster or slower by input.
* Penalties are no longer in $[0, k]$: the total grows with the schedule, and only differences between schedules
  mean anything, as before.
* The tuned trade-off between a shift of imbalance, a disliked pairing and an hour of short rest holds at any
  length, so the defaults should carry over to longer schedules; the 48-hour check is still to come.
