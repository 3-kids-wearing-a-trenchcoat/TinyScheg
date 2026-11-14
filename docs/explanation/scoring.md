# Scoring

> [!IMPORTANT]
> **Implemented.** This page is the specification for TinyScheg's scoring, implemented in
> [`scoring`](../reference/api/scoring.md) and used by branch and bound to find the best schedule.
> See [ADR 0005](../decisions/0005-weighted-sum-of-normalized-penalties.md),
> [ADR 0006](../decisions/0006-convex-function-for-workload-fairness.md),
> [ADR 0012](../decisions/0012-deterministic-path-independent-scoring.md),
> [ADR 0013](../decisions/0013-availability-weighted-workload.md),
> [ADR 0014](../decisions/0014-exact-worst-rest-deficit.md),
> [ADR 0021](../decisions/0021-power-function-for-workload-fairness.md),
> [ADR 0022](../decisions/0022-scoring-parameters-with-defaults-and-input-overrides.md),
> [ADR 0032](../decisions/0032-flat-penalty-parts.md) and
> [ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md).
> This page was corrected on 2026-11-10 and the corrections confirmed on 2026-11-11; see [Corrections](#corrections).
> Parameter defaults are listed under [Parameters](#parameters).

## General idea

Each schedule state — **including incomplete schedules** — has a score. Scores are monotonically non-decreasing
*penalties*: each state's penalty is greater than or equal to the penalty of its parent state.

The penalty is a sum of the penalties given by each worker, which is analogous to each worker saying how much they
*dislike* the schedule as it currently stands. Each worker's penalty is calculated separately, from the current
assignment and constants computed for that worker before the search. This is done by a planned `scoring` package;
workers themselves hold no scoring state.

The penalty is what makes the [pocket](search-algorithm.md#branch-and-bound-the-pocket) work: once a complete,
legal schedule has been found, any partial schedule whose penalty is already higher can be pruned, since its
penalty can only grow.

The penalty must also be **deterministic and path-independent**: for a given configuration of weights and
parameters, every state maps to exactly one penalty, regardless of how the search reached it
(see [ADR 0012](../decisions/0012-deterministic-path-independent-scoring.md)). Every formula below depends only on
the current assignment and on constants computed before the search, so this holds as long as the computation itself
is deterministic (e.g. sums are always taken in the same order).

## Calculations

Each *criterion* (likes/dislikes, workload, rest) has its own penalty function, each measured in **fixed units**, so
that one event (a disliked pairing, a shift of imbalance, a worker's hours of short rest) costs the same whatever
the schedule's length ([ADR 0032](../decisions/0032-flat-penalty-parts.md)). Their **weighted sum** is the total penalty.
Only differences between schedules matter: a penalty that every schedule carries changes no comparison, so the total
growing with the schedule's size doesn't matter.

The search keeps the scores it steers by incrementally, derived from their previous values, and scores what
decides its result from scratch ([ADR 0027](../decisions/0027-incremental-scoring-for-steering.md)).
A proper score must be produced for every single state, since its absolute value is compared with the pocket's —
scores can't be calculated lazily.

### Definitions

* $W = \lbrace w_1, w_2, \dots , w_k \rbrace$ is the set of all workers ($k \in \mathbb{N}$ is the total number of
  workers).
* For every worker $w_i \in W$, let $L_i \subset W$ be the group of workers that $w_i$ likes.
* For every worker $w_i \in W$, let $H_i \subset W$ be the group of workers that $w_i$ dislikes. It is assumed that
  $\forall i \in [1,k] \quad L_i \cap H_i = \emptyset$, and that a worker appears in neither of their own groups.
* For every worker $w_i \in W$, let $\mathrm{av}_i \geq 0$ be $w_i$'s **availability**: the total number of hours
  **within the schedule period** during which $w_i$ is available.
* $S = \lbrace s_1, s_2, \dots ,s_n \rbrace$ is the set of all slots ($n\in \mathbb{N}$ is the total number of slots).
  For a slot $s$, $[s]_\text{start}$ and $[s]_\text{end}$ are its start and end times, and $|s|$ is its
  **duration** in hours.
* For every slot $s_i \in S$, let $D_i \subseteq W$ be **the domain** of $s_i$.
* The notation $s_i \sim s_j$ means that $s_i$ and $s_j$ **belong to the same shift**.
  * For every slot $s_i \in S$, the set $\mathcal{S}(s_i) = \lbrace s_j \in S \mid s_i \sim s_j \rbrace$ is the shift
    $s_i$ belongs to.
    Notice that $s_i \sim s_i \Leftrightarrow s_i \in \mathcal{S}(s_i)$, that if $s_j \sim s_i$ then
    $\mathcal{S}(s_i) = \mathcal{S}(s_j)$, and that for every $s_i, s_j \in S$ such that $s_i \nsim s_j$,
    $\mathcal{S}(s_i) \cap \mathcal{S}(s_j) = \emptyset$.
  * A slot is **shared** if its shift has more than one slot, i.e. $|\mathcal{S}(s)| > 1$. Let $n_\text{shared}$ be
    the total number of shared slots.
* $\mathcal{A}_i: S^{n \in \mathbb{N}} \rightarrow W^n$ is a function that takes a set of slots and returns the
  workers **assigned** to these slots in the $i$-th iteration of the run.
  $\mathcal{A}$ (no subscript) refers to the workers assigned to the input slots at the *current* iteration.
* The notation $s_i \bowtie s_j$ means that the slots $s_i$ and $s_j$ are **diff constrained** (they must have
  different assignments).
  * $C = \lbrace (s_i, s_j) \in S \times S \mid s_i \bowtie s_j \rbrace$ is the **constraint set**, the set of pairs of
    slots which are diff constrained.
  * $C_i = \lbrace s_j \in S \mid s_i \bowtie s_j \rbrace$ is **the constraint set of $s_i \in S$ specifically**.
* For every iteration $t \in \mathbb{N}$ and worker $w_i \in W$, $A_t(w_i)$ is **the set of slots $w_i$ is assigned
  to at iteration $t$**.
* $m \in \mathbb{R}^+$ is **the minimum rest period** in hours, as defined in the hard constraints. Since slots that
  are less than $m$ hours apart are diff constrained, any two slots assigned to the same worker are at least $m$
  hours apart.

### Likes/dislikes

Let $l_i(x)$ be the **like function** for worker $w_i$:

$$
l_i(x) = \begin{cases} 0 & x \in L_i \\ \alpha & x \notin L_i \cup H_i \\ \beta & x \in H_i \end{cases}
$$

such that $\alpha ,\beta \in \mathbb{R}$ and $0 < \alpha < \beta / 2$.
That is, liked workers produce no penalty, workers who are neither liked nor disliked produce a relatively small
penalty, and disliked workers produce a bigger penalty. Since the like score is divided by $\beta$ to normalize it
(below), only the ratio $\alpha / \beta$ matters; it's a [parameter](#parameters), 0.44 by default. Dislikes are soft:
they're discouraged, never forbidden.

**A dislike outweighs a like** ([ADR 0023](../decisions/0023-dislikes-outweigh-likes.md)). Each worker rates their
partners from their own lists, so a pair costs the sum of both sides' ratings. Measured from a neutral pairing, a
like saves $\alpha$ and a dislike costs $\beta - \alpha$; keeping $\alpha / \beta$ below 1/2 makes the dislike
count more. With the default 0.44, a dislike counts about 1.27 times as much as a like, enough that a pair where
one likes the other and the other dislikes them costs more than a neutral pair
([ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)):

| Pair (each side's view of the other) | Cost, with $\beta = 1$ and $\alpha = 0.44$ |
|---|---|
| both like each other | 0 |
| one likes, the other is neutral | 0.44 |
| both neutral | 0.88 |
| one dislikes, the other likes them | 1 — worse than a neutral pair, not cancelled out |
| one dislikes, the other is neutral | 1.44 |
| both dislike each other | 2 |

At $\alpha / \beta = 1/2$, a dislike and a like would cancel out exactly (a dislike/like pair would cost the same
as a neutral one), and above it a like would outweigh a dislike, so the `neutral_partner` setting must be below 1/2.
This limits the setting only: disliked pairings are still allowed, just penalized.

At iteration $t \in \mathbb{N}$, the **local like function** $\mathcal{L}_t:W \times S \rightarrow \mathbb{R}$ is
($| \cdot |$ denoting the **size** of $\cdot$):

$$
\mathcal{L}_t(w_i, s_i) = \frac{1}{| \mathcal{S}(s_i) | - 1} \cdot \sum_{w \in A_t \big( \mathcal{S}(s_i) \setminus \lbrace s_i \rbrace \big)} l_i(w) = \sum_{w \in A_t \big(\mathcal{S}(s_i) \setminus \lbrace s_i \rbrace \big)} \frac{l_i(w)}{| \mathcal{S}(s_i) | - 1}
$$

Or less formally: $\mathcal{L}_t (w_i, s_i)$ is **the sum of the like function of $w_i$ over the workers assigned to
the *other* slots of $s_i$'s shift, averaged over the number of other slots in that shift**. Other slots of the shift
that are still unassigned contribute nothing.
If a shift has only one slot, this function is defined to be 0, that is,
$| \mathcal{S} (s_i) | = 1 \Rightarrow \forall w_i \in W \; \forall t \in \mathbb{N} \quad \mathcal{L}_t(w_i,s_i)=0$.

For each worker $w_i \in W$, the **total like score** $\mathcal{L}_t: W \rightarrow \mathbb{R}$ at iteration
$t\in \mathbb{N}$ is:

$$
\mathcal{L}_t(w_i) = \sum_{s \in A_t(w_i)} \mathcal{L}_t(w_i,s)
$$

That is, the sum of the local like function for $w_i$ over all the slots $w_i$ is currently assigned to.
The **global like score** at iteration $t\in \mathbb{N}$ is the sum of all workers' like scores:

$$
\mathcal{L}^{*}(t) = \sum _{w \in W} \mathcal{L}_t(w)
$$

**Monotonicity:** assigning a worker $w_j$ to a slot $s$ adds a new non-negative term $\mathcal{L}_t(w_j, s)$, and
adds $\frac{l_i(w_j)}{|\mathcal{S}(s)| - 1} \geq 0$ to the term of every worker $w_i$ already assigned to another slot
of the same shift. Nothing decreases.

#### The like score's units

**The global like score** is measured in units of $\beta$, a disliked partner, as in the original design
([ADR 0032](../decisions/0032-flat-penalty-parts.md)):

$$
\mathcal{L}^{**}(t) = \frac{\mathcal{L}^*(t)}{\beta}
$$

so one disliked pairing costs the same in any schedule. It's 0 if every shift has a single slot.

The divisor must be a constant. Normalizing each worker by their *own* number of shifts (an average) would break
monotonicity, since an average can decrease when a liked shift is added.

### Workload

Let $w_i \in W$ be a worker with $\mathrm{av}_i > 0$, $t \in \mathbb{N}$, and let $h_t(w_i) \geq 0$ be $w_i$'s
**workload** at iteration $t$: the ratio between the load assigned and the hours available.

$$
h_t(w_i) = \frac{\text{Total load assigned to } w_i}{\mathrm{av}_i} = \frac{\sum _{s \in A_t(w_i)} \ell(s)}{\mathrm{av}_i}
$$

A slot's **load** $\ell(s)$ blends its length with one average slot
([ADR 0026](../decisions/0026-workload-counts-shifts-and-hours.md)), since workers feel both the hours they work and
the number of times they have to show up: three short shifts weigh more than one long one of the same hours.

$$
\ell(s) = (1 - \sigma) \, |s| + \sigma \, \bar{L}
$$

where $\bar{L}$ is the mean length of all the schedule's slots (each schedule sets its own norm) and
$\sigma \in [0, 1]$ is the **shift share** (by default 0.5; see [Parameters](#parameters)). With $\sigma = 0$ only
hours count; with $\sigma = 1$ every shift counts the same, however long. The blend keeps the total: the load of all
slots together equals their hours. Naturally, $h_t(w_i)=0$ iff $A_t(w_i) = \emptyset$. With $\sigma = 0$,
$h_t(w_i) \leq 1$, since a worker's slots lie within their availability and never overlap; with $\sigma > 0$, a
worker with many short shifts can exceed 1, which the normalization below takes care of.
Workers with $\mathrm{av}_i = 0$ can't be assigned anywhere and are left out of the workload penalty.

The absolute workload of each worker doesn't matter; what matters is that it's as **fair** as possible, meaning
workloads — each worker's share of their *own* availability — should be as equal as possible. Unavailable time
counts as neither work nor rest. The workload penalty function is built from a function $\varphi$, as follows.

#### The function $\varphi$ and Jensen's inequality

We use a **convex, monotonically increasing** function $\varphi :\mathbb{R} \rightarrow \mathbb{R}$ with
$\varphi(0) = 0$, and take advantage of the weighted form of
[Jensen's inequality](https://en.wikipedia.org/wiki/Jensen%27s_inequality#Finite_form).

**Jensen's inequality** states (in the special case relevant here) that for a real convex function $\varphi$,
numbers $x_1,\dots, x_n$ in its domain and positive weights $\lambda_1, \dots, \lambda_n$:

$$
\varphi \left( \frac{\sum \lambda_i x_i}{\sum \lambda_i} \right) \leq \frac{\sum \lambda_i \varphi (x_i)}{\sum \lambda_i}
\quad \Rightarrow \quad
\left( \sum \lambda_i \right) \varphi (\overline{x}) \leq \sum_{i=1}^n \lambda_i \varphi (x_i)
\quad \text{where} \quad \overline{x} = \frac{\sum \lambda_i x_i}{\sum \lambda_i}
$$

with equality when $x_1 = \dots = x_n$ (and, for strictly convex $\varphi$, only then).

We choose $x_i = h_t(w_i)$ and $\lambda_i = \mathrm{av}_i$. In a complete schedule every slot is filled, so the total
assigned load $T = \sum_i \mathrm{av}_i \, h_t(w_i)$ is the same for every complete schedule, and so is
$\overline{x} = T / \sum_i \mathrm{av}_i$. The left-hand side is therefore a constant, and the penalty

$$
\mathcal{W}(t) = \sum_{i=1}^k \mathrm{av}_i \, \varphi \big( h_t(w_i) \big)
$$

is **minimal exactly when every worker's workload is the same**, which is what we're looking for. The advantage of
this function is that we don't need to know (or even guess) what that common workload is.

The weights are essential. Without them, $\sum \varphi(h_t(w_i))$ would only be minimized by equal workloads if
$\sum h_t(w_i)$ were fixed, which it isn't: when availabilities differ, the unweighted sum favours giving
disproportionately many hours to the most available workers (see
[ADR 0013](../decisions/0013-availability-weighted-workload.md)).

It also behaves well step by step. Assigning a slot of duration $|s|$ to $w_i$ increases $\mathcal{W}$ by
$\mathrm{av}_i \big( \varphi(h + |s|/\mathrm{av}_i) - \varphi(h) \big) \approx |s| \cdot \varphi'(h)$, where $h$ is
$w_i$'s current workload. Since $\varphi$ is convex, $\varphi'$ is increasing: **the higher a worker's workload, the
higher the penalty for giving them another assignment**, regardless of how available they are.

There are two "low-hanging fruit" options for $\varphi$:

1. $\varphi (x) = x^p$ where $p>1$
2. $\varphi (x) = e^{ax} - 1$ where $a > 0$

Generally speaking, $x^p$ and $e^{ax} -1$ penalize harder as $p$ and $a$ increase respectively, and $e^{ax} - 1$ is
*much stricter* (penalizes harder) than $x^p$.

> [!NOTE]
> **Decided:** $\varphi(x) = x^p$ with a whole number $p \geq 2$, by default $p = 2$
> ([ADR 0021](../decisions/0021-power-function-for-workload-fairness.md)). With $p = 2$, minimizing the penalty is
> the same as minimizing the availability-weighted variance of the workloads. It can be computed exactly, and on the
> example input it pulled harder towards fairness than $e^{ax} - 1$ at the same scale. The exponential is described
> here for the reasoning only.

![Plot of x^p and e^(ax) - 1 on the range [0, 1]](../images/workload-phi-functions.png)

> Pictured: $x^p$ (in purple) and $e^{ax} -1$ (in red) on the range $[0,1]$, with $p$ and $a$ chosen to almost
> intersect at $x=1$. Increasing $p$ "moves the midpoint" to the right, whereas increasing $a$ makes the ascent much
> sharper.

**Monotonicity:** assigning a slot only increases the assigned worker's $h_t$, and $\varphi$ is increasing, so
$\mathcal{W}$ never decreases.

#### The workload's units

The workload penalty is measured in **workload units** ([ADR 0032](../decisions/0032-flat-penalty-parts.md)): the
term $\mathrm{av} \cdot \varphi(h)$ of an average worker given one average slot,

$$
u_W = \frac{\bar{\ell}^{\,p}}{\overline{\mathrm{av}}^{\,p-1}}
$$

where $\bar{\ell}$ is the mean slot load and $\overline{\mathrm{av}}$ the mean availability of the workers with any.
**The global workload function** is

$$
\mathcal{W}^*(t) = \frac{1}{u_W} \sum_{i=1}^k \mathrm{av}_i \, \varphi \big( h_t(w_i) \big)
$$

and 0 if no worker has any availability. With $p = 2$, moving one average slot between two average workers with
the same load costs 2 units, whatever the schedule's length: a fixed number of extra shifts, which is how workers
count, always costs the same. ($u_W$ is a constant, so the penalty remains monotone, and it's still minimal exactly
when every worker's workload is the same.)

Earlier, the workload was divided by its largest possible value, each worker packed with as much load as the hard
constraints allow ([ADR 0015](../decisions/0015-normalize-workload-by-packable-maximum.md), superseded). That value
grows with availability, as does the share one shift is of it, so a shift of imbalance cost about 1/length², and
long schedules all but stopped weighing fairness.

The workload never gets near 0 for a complete schedule: the hours that must be worked have a minimum cost, reached
when workloads are equal (by Jensen's inequality, $\left(\sum_i \mathrm{av}_i\right) \varphi(\overline{x})$ before
dividing). That cost is the same for every schedule, so it changes no comparison.

### Rest

The workload function accounts for fairness in workload, but not for needlessly cramming many shifts for one worker
as close together as possible. That is, for otherwise identical shifts, it doesn't penalize a situation in which
worker A is given $X$ shifts that each start as soon as A's minimum rest period (the hard constraint) is over,
while worker B gets very spread-out shifts.

That said, rest periods shouldn't necessarily all be made as similar as possible, especially in an asynchronous
schedule. An ideal rest period following a 3-hour shift can and should be shorter than one following a 4-hour (or
longer) shift. (Since [ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md), a rest's target comes from both shifts around it, so that the same two shifts cost the
same in either order: a rest next to a longer shift should be longer, whichever side it's on.)
A rest period longer than the ideal doesn't need to be penalized either, since the main problem with an overly long
rest period is the risk of it coming at the expense of someone else — and that is already reflected as a shorter
rest for that someone else. If it's possible to give worker X extra rest without it coming at someone's expense, X
should get it.

For these reasons, a fairly simple function suffices: it calculates a **rest deficit** for each rest period of each
worker, sums them up per worker, and adds up a convex function of each worker's total.

> [!NOTE]
> **Implemented**, as below since 2026-11-14 ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)): the targets are derived from the input rather than set
> by a rest factor chosen by hand, a rest's target comes from both shifts around it, and each worker's total is
> squared. The provable properties this is meant to have are tests (`tests/test_rest_properties.py`).

Let $w \in W$ be some worker, and $A_t(w)$ all the slots $w$ is assigned to at iteration $t \in \mathbb{N}$.
Let $A_t(w) = ( s_1, s_2 ,\dots , s_n)$ be ordered by **`DateTimeRange`**, meaning that for every
$s_i , s_j \in A_t(w)$:

$$
s_i < s_j \iff \bigg( [s_i]_\text{start} < [s_j]_\text{start} \bigg) \text{ OR } \bigg( [s_i]_\text{start} = [s_j]_\text{start} \text{ AND } [s_i]_\text{end} < [s_j]_\text{end} \bigg)
$$

(A worker's slots never overlap, so this order is strict and unambiguous.)

For every $s_i \in A_t(w)$, define the **rest period** after $s_i$, the time between it and $w$'s next shift that
$w$ is available ([ADR 0038](../decisions/0038-rests-count-only-available-time.md)):

$$
\Delta s_i = \begin{cases} [s_{i+1}]_\text{start} - [s_i]_\text{end} - u_w\big([s_i]_\text{end}, [s_{i+1}]_\text{start}\big) & i \neq n \\ \infty & i=n \end{cases}
$$

where $u_w(t_1, t_2)$ is how many hours of $w$'s unavailability fall between $t_1$ and $t_2$. Unavailable time is
neither work nor rest, as in the workload part, whatever the reason for it: a rest spanning an absence is judged by
the time available around it. (The hard minimum rest stays on the clock.)

and, for $i \neq n$, the **rest target** between $s_i$ and $s_{i+1}$: the mean of the two shifts' durations times
the **rest factor** $\gamma$,

$$
r(s_i) = \gamma \cdot \frac{|s_i| + |s_{i+1}|}{2}, \qquad \gamma = \frac{\sum_{w \in W} \mathrm{av}_w - H}{H}
$$

where $H = \sum_{s \in S} |s|$ is the total length of all slots. $\gamma$ is the schedule's free hours per hour of
work, derived from the input (over the whole schedule, history included,
[ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md)) rather than chosen: since fair shares
of work are proportional to availability, it's every worker's free time divided by their fair share, so a worker
who works their share, spread evenly, gets exactly their share of free time around each shift. Each shift sits in
the middle of its share, half before it and half after; nothing is assumed about which side of a shift its demand
falls on. With every shift the same length, the target is $\gamma \cdot |s_i|$; on the example, $\gamma \approx 3.46$.

(All time periods are in hours.)

For every $w \in W$ and $s \in A_t(w)$, the **rest deficit function** $d_t(w,s)$ is:

$$
d_t(w,s) = \max \bigg( 0, \; r(s) - \Delta s \bigg)
$$

That is, $d_t(w,s)$ is how many hours **below** the rest target worker $w$ actually rested after shift $s$.
If $w$'s rest period after $s$ was equal to or greater than the rest target, $d_t(w,s) = 0$; how much longer it
was doesn't matter. In particular, $d_t(w, s_n) = 0$ for a worker's last shift.

The **worker rest deficit function** at iteration $t$ is:

$$
\mathcal{R}_t(w) = \sum _{s \in A_t(w)} d_t(w,s)
$$

That is, the sum of the rest deficits for each shift $w$ is assigned to at iteration $t$.

> **Monotonicity:** assigning $w$ another slot $s'$ can only add deficit.
> * If $s'$ falls between two of $w$'s slots $s_i < s' < s_{i+1}$, the one rest between them becomes two. Their
>   periods add up to *less* than the old one,
>   $\big([s']_\text{start} - [s_i]_\text{end}\big) + \big([s_{i+1}]_\text{start} - [s']_\text{end}\big) = \Delta s_i - |s'|$,
>   and their targets to *more*, $\gamma \frac{|s_i| + |s'|}{2} + \gamma \frac{|s'| + |s_{i+1}|}{2} = r(s_i) + \gamma |s'|$.
>   So the two deficits, each at least 0 and together at least
>   $\big(r(s_i) + \gamma |s'|\big) - \big(\Delta s_i - |s'|\big) \geq r(s_i) - \Delta s_i$, add up to at
>   least the old one.
> * If $s'$ comes after $w$'s last slot, the rest after that slot goes from $\infty$ (no deficit) to a finite value,
>   so its deficit can only grow (from 0), and $d_t(w, s') = 0$.
> * If $s'$ comes before $w$'s first slot, it only adds a new deficit $d_t(w, s') \geq 0$.
>
> No other deficit changes, so $\mathcal{R}_t(w)$ never decreases.

Similarly, the **global rest deficit function** at iteration $t$ is:

$$
\mathcal{R}^*_t = \sum _{w \in W} \mathcal{R}_t(w) = \sum _{w \in W} \Bigg( \sum _{s \in A_t(w)} d_t(w,s) \Bigg)
$$

#### Scaling the rest deficit

The minimum possible deficit for any worker at any slot is 0. Since any two slots assigned to the same worker are at
least $m$ hours apart on the clock, $\Delta s \geq m$ unless the worker is unavailable in between, so for a worker
available throughout, the maximum possible deficit of a rest is reached when the next shift starts as soon as the
minimum rest period is over:

$$
d_m(s) = \max \big(0, \; r(s) - m \big)
$$

If $r(s) \leq m$, the minimum rest period already meets the rest target and that rest can never fall short. With a
rest factor chosen by hand (2.5, before ADR 0036), that silenced the rest part after short shifts: with 6 hours'
minimum rest, after any shift of 2.4 hours or less. With $\gamma$ derived from the input, it happens only where
spreading a worker's fair share evenly would give them no more than the minimum rest anyway: then resting at the
minimum is what even spacing gives. (A worker who gets fewer shifts than their share has room the target doesn't
see; among the benchmark inputs, `sweep_02`, whose 2-hour targets come out at exactly 6 hours.)

Normalizing each deficit by $d_m(s)$ isn't very helpful, because the number of rest periods varies; normalization
should instead be relative to *each worker*, whose number is constant for a given schedule.

For every $w \in W$, let $M_w \geq 0$ be **the worst possible deficit** for $w$: the largest value
$\mathcal{R}_t(w)$ could take over any legal set of slots $w$ could be assigned to (calculating $M_w$ is covered in
the next section). **The normalized worker rest deficit function** is
$\frac{1}{M_w} \sum _{s \in A_t(w)} d_t(w,s) = \sum _{s \in A_t(w)} \frac{d_t(w,s)}{M_w}$, which lies between 0
(best case) and 1 (worst case). If $M_w = 0$, $w$ can never have a deficit and the term is defined to be 0.
To keep the average hour short costing the same at any schedule length, it's multiplied by $\bar{M}$, the mean
$M_w$ of the workers who could have a deficit ([ADR 0032](../decisions/0032-flat-penalty-parts.md)); without
$\bar{M}$, every $M_w$ grows with the schedule, and an hour short would cost about 1/length.

Each worker's total is then **squared** ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)), so that the same shortfall costs more on a worker who already
has some, the history included: it's spread rather than concentrated, and a worker who has had short rests is made
up to, as with workload. The square is taken in units of one typical target, $\tau = \gamma \cdot \overline{|s|}$
($\overline{|s|}$ the mean slot length; also derived from the input), so it doesn't depend on the unit of time.
Therefore, **the global rest deficit function** is:

$$
\mathcal{R}^{**}(t) = \sum _{w \in W} \frac{\bar{M}}{M_w} \cdot \frac{\mathcal{R}_t(w)^2}{\tau}
$$

Each worker's total only grows, so its square does, and $\mathcal{R}^{**}$ is monotone. A worker's first
hours short cost less than before and later ones more: at half a typical target short, an hour costs what it did
with the sum alone. Without the square, the same total cost the same however it was shared out, and putting it all
on one worker, at the minimum rest while others rested far longer, was as cheap as spreading it (measured on
2026-11-14, ADR 0036).

Normalizing **per worker** is deliberate. Each worker's rest is judged relative to their *own* worst case, just as
their workload is judged relative to their *own* availability. As a result, an hour of deficit weighs more for a
worker whose availability allows only a mild worst case than for a highly available one. This follows the same idea
of fairness as the workload policy, in which unavailable time — leave, other duties, being posted elsewhere — counts
as neither work nor rest.

#### Calculating the worst possible deficit $M_w$

$M_w$ is calculated **exactly**, as the most expensive path in a
[directed acyclic graph](https://en.wikipedia.org/wiki/Directed_acyclic_graph) (DAG)
(see [ADR 0014](../decisions/0014-exact-worst-rest-deficit.md)):

* the nodes are the slots $w$ could fill (after unary pruning). With a history, a history slot is a node for every
  worker who could have filled it in its own period (in that period's input, available for it, with its role then),
  not only for the one who did: being passed over doesn't change a worker's worst case, being unavailable does
  ([ADR 0037](../decisions/0037-worst-rest-deficit-from-scratch-over-the-history.md));
* there is an edge $s \rightarrow s'$ whenever $w$ could work $s$ and then $s'$ as consecutive shifts, i.e.
  $[s']_\text{start} - [s]_\text{end} \geq m$;
* the edge's weight is the deficit it causes, $\max \big(0, \; \gamma \cdot \frac{|s| + |s'|}{2} - \Delta \big)$, where
  $\Delta$ is the rest between $s$ and $s'$ in available time, as above.

Every legal sequence of $w$'s shifts is a path in this graph, and its total deficit is the path's total weight, so
$M_w$ is the weight of the heaviest path. Sorting the slots by time and applying a standard
[longest-path algorithm for DAGs](https://www.geeksforgeeks.org/dsa/find-longest-path-directed-acyclic-graph/)
takes $O(n^2)$ time for $n$ slots, which is cheap at the intended schedule sizes.

The search space can be reduced by looking at **time ranges** rather than distinct slots: in terms of rest deficit,
a shift from $t_1$ to $t_2$ is the same no matter which slot it's spent in.

If these calculations ever become too slow, they can be sped up by limiting the possible first shifts: if a worker's
first shift starts at time $t$ and some shift ends before $t - m$, another shift could be added before it, so the
worst-case sequence **must start with a shift within $m$ hours of the schedule start**.

## Total score for each state

For an iteration $t \in \mathbb{N}$ and three weights $a,b,c \geq 0$ such that $a + b + c = 1$ (by default
9/34, 20/34 and 5/34, i.e. 0.45 : 1 : 0.25; see [Parameters](#parameters)), the penalty function $\mathcal{P}(t)$
is the weighted sum:

$$
\mathcal{P}(t) = a \cdot \mathcal{L}^{**}(t) + b \cdot \mathcal{W}^*(t) + c \cdot \mathcal{R}^{**}(t)
$$

(The weight $a$ here is unrelated to the parameter $a$ of $\varphi(x) = e^{ax} - 1$.)

The weights are what each part is multiplied by. Since each part is in fixed units, they set how one event of each
kind trades against the others, the same at any schedule length. $\mathcal{P}(t) \geq 0$; it has no fixed upper
bound, and only differences between schedules mean anything.

Each sub-function is monotonically non-decreasing, and the weights are non-negative, so $\mathcal{P}$ is too.

## Parameters

> [!NOTE]
> **Implemented**: [`ScoringParameters`](../reference/api/schedule-input.md#class-scoringparameterslikes_weight-workload_weight-rest_weight-workload_power-neutral_partner-shift_share)
> and the `scoring` input settings. Decided in
> [ADR 0022](../decisions/0022-scoring-parameters-with-defaults-and-input-overrides.md).

Every parameter has a default, defined once as a named constant in the code, and can be overridden in the optional
`scoring` section of the input's settings (see [Input format](../reference/input-format.md#scoring)).

| Parameter | Symbol | Default | Input field | Allowed values |
|-----------|--------|---------|-------------|----------------|
| Weights of likes, workload and rest | $a$, $b$, $c$ | 9/34, 20/34, 5/34, i.e. 0.45 : 1 : 0.25 ([ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)) | `weights: {likes, workload, rest}` | at least 0, not all 0; divided by their sum |
| Workload power | $p$ | 2 | `workload_power` | a whole number, at least 2 |
| Neutral partner, relative to a disliked one | $\alpha / \beta$ | 0.44 ([ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)) | `neutral_partner` | more than 0, less than 1/2 ([ADR 0023](../decisions/0023-dislikes-outweigh-likes.md)) |
| Shift share of a slot's load | $\sigma$ | 0.5 | `shift_share` | from 0 to 1 ([ADR 0026](../decisions/0026-workload-counts-shifts-and-hours.md)) |

The rest factor $\gamma$ is no longer a parameter: it's derived from the input ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md); before, it was set by hand,
2.5 by default, [ADR 0028](../decisions/0028-rest-factor-default-2-5.md)).

What the defaults mean on the example input (`exampleInput.yml`: 9 workers, 17 slots, 24 hours), as what one event
costs for a worker of average availability and worst case, with shifts of the average length (2.8 hours; computed
by `tools/tune.py`'s unit trade-offs, 2026-11-14):

| Event | Before weights | Weighted |
|-------|----------------|----------|
| A like, instead of a neutral partner | 0.44 | 0.12 |
| A dislike, instead of a neutral partner | 0.56 | 0.15 |
| A worker's first short rest (an average shift's length below target) | 0.82 | 0.12 |
| Their second | 2.45 | 0.36 |
| One worker resting at the minimum twice (6 hours, 3.8 below the target each time) | 5.81 | 0.85 |
| One extra shift (the others taking one fewer between them) | 1 | 0.59 |
| An avoidable gap of two shifts (one shift moved between two workers with the same load) | 2 | 1.18 |

* **The user's trade-offs** ([ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)), which the
  defaults were chosen to keep, and `tests/test_default_tradeoffs.py` checks: a like is worth about one short rest;
  a dislike a little more than a like; a second short rest more than any one pairing; and an avoidable gap of two
  shifts more than three pairings, and more than one worker resting at the minimum twice.
* **The same at any length** ([ADR 0032](../decisions/0032-flat-penalty-parts.md)): a gap of two shifts and a
  pairing cost the same at 48 hours as at 24.
* **Rest:** an hour short doesn't cost a fixed amount, since each worker's shortfall is squared
  ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)). On the example, one typical
  target is $\tau \approx 9.8$ hours, and for a worker with an average worst case, the first hour short costs +0.10
  before weights (+0.015 weighted), the second +0.31 (+0.045), the fifth +0.92 (+0.14), the tenth +1.95 (+0.29).
* **Workload:** a gap in 4-hour shifts costs about 1.4 times a gap in 3-hour ones (2.9 against 2.1 before weights).
  With hours alone it would be about 1.8 times ($(4/3)^2$); with the shift share at 0.5, part of each shift's load is
  the same whatever its length.
* On other inputs these ratios differ, most of all for rest: what resting at the minimum costs depends on how far
  the minimum sits below the schedule's targets, which a gap of two shifts doesn't (see ADR 0039's consequences).

Scores are floating-point numbers. Computed from scratch, with sums always taken in the same order, the same state
always gets exactly the same score, and since every operation involved is monotone under rounding, a state never
scores lower than its parent. The search also keeps scores incrementally, which can differ by rounding (about
$10^{-14}$), but only to steer by; whatever decides its result is computed from scratch ([ADR 0027](../decisions/0027-incremental-scoring-for-steering.md)).

## Corrections

This page was originally transferred as-is from the design notes. It was reviewed and corrected on 2026-11-10, and
the corrections were confirmed on 2026-11-11:

1. **Rest target.** It was written as $r(s_i) = \gamma \big([s_{i+1}]_\text{start} - [s_i]_\text{end}\big)$, i.e.
   $\gamma$ times the rest period itself, which made the deficit $(\gamma - 1) \cdot \Delta s_i$: the longer the
   rest, the larger the penalty, and the target could never be met. It's now $\gamma \cdot |s_i|$, as the text
   ("shift length times $\gamma$") and the normalization already intended. The same typo appeared in the derivation
   of $d_m(s)$.
2. **Workload weighting.** The penalty was the unweighted $\sum \varphi(h_t(w_i))$, which isn't minimized by equal
   workloads when availabilities differ. It's now weighted by availability; see
   [ADR 0013](../decisions/0013-availability-weighted-workload.md).
3. **Workload normalization.** The two choices of $\varphi$ were normalized inconsistently ($[0,1]$ for $x^p$,
   $[0,k]$ for $e^{ax} - 1$). Both are now normalized to $[0, k]$.
4. **Likes normalization.** $\mathcal{L}^*/\beta$ grew with the number of shifts rather than being bounded by $k$,
   so the weights' meaning depended on the schedule's size. It was then divided by its maximum,
   $\beta \cdot n_\text{shared}$, and scaled to $[0,k]$. *Undone on 2026-11-12*
   ([ADR 0032](../decisions/0032-flat-penalty-parts.md)): that made a disliked pairing cost less the longer the
   schedule, and the original $\mathcal{L}^*/\beta$ is back.
5. **Likes self-inclusion.** The local like function summed over the whole shift, including the worker's own slot,
   so every worker rated themselves as neutral. It now sums over the *other* slots of the shift only.
6. **Worst rest deficit.** $M_w$ was to be found with a greedy algorithm, described as an upper bound. A greedy
   algorithm finds one actual sequence of shifts, whose deficit is a *lower* bound on the worst case, so the
   normalized rest penalty could exceed 1. $M_w$ is now calculated exactly; see
   [ADR 0014](../decisions/0014-exact-worst-rest-deficit.md).
7. **Rest monotonicity argument.** The original argument stated
   $\Delta(s_1, s_3) < \Delta(s_1, s_2), \Delta(s_2, s_3) < \Delta(s_1,s_2) + \Delta (s_2,s_3)$, which has every
   inequality reversed. The conclusion (the rest penalty is monotone) was correct; the argument has been replaced.
8. **Edge cases.** Terms that would divide by zero ($\mathrm{av}_i = 0$, $n_\text{shared} = 0$, $M_w = 0$, and a
   zero workload denominator) are now defined.
9. **Workload scale.** The workload penalty was normalized by a workload of 1 (every available hour worked), which
   the minimum rest period makes unreachable; typical schedules used only a small fraction of that range. It's now
   normalized by each worker's packable maximum; see
   [ADR 0015](../decisions/0015-normalize-workload-by-packable-maximum.md). *Replaced on 2026-11-12* by fixed workload
   units ([ADR 0032](../decisions/0032-flat-penalty-parts.md)), since the packable maximum made a shift of imbalance
   cost about 1/length².
