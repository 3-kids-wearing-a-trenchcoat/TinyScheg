# Scoring

> [!IMPORTANT]
> **Partially implemented.** This page is the specification for TinyScheg's scoring. The parameters and the
> constants calculated before the search ([`scoring`](../reference/api/scoring.md)) are implemented; the penalties
> themselves aren't yet.
> See [ADR 0005](../decisions/0005-weighted-sum-of-normalized-penalties.md),
> [ADR 0006](../decisions/0006-convex-function-for-workload-fairness.md),
> [ADR 0012](../decisions/0012-deterministic-path-independent-scoring.md),
> [ADR 0013](../decisions/0013-availability-weighted-workload.md),
> [ADR 0014](../decisions/0014-exact-worst-rest-deficit.md) and
> [ADR 0015](../decisions/0015-normalize-workload-by-packable-maximum.md),
> [ADR 0021](../decisions/0021-power-function-for-workload-fairness.md) and
> [ADR 0022](../decisions/0022-scoring-parameters-with-defaults-and-input-overrides.md).
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

Each *criterion* (likes/dislikes, workload, rest) has its own penalty function. Each function is **normalized** so
that its value lies between $0$ and $k$ (the number of workers), and their **weighted sum** is the total penalty.

Ideally, each score would be derived from its previous value to make these calculations more efficient, but how
practical that is remains to be seen (see [Future work](future-work.md#incremental-scoring)).
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

such that $\alpha ,\beta \in \mathbb{R}$ and $0 < \alpha < \beta$.
That is, liked workers produce no penalty, workers who are neither liked nor disliked produce a relatively small
penalty, and disliked workers produce a bigger penalty. Since the like score is divided by $\beta$ to normalize it
(below), only the ratio $\alpha / \beta$ matters; it's a [parameter](#parameters), 1/3 by default. Dislikes are soft:
they're discouraged, never forbidden.

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

#### Normalizing the like score

Each local like term is an average of values that are at most $\beta$, so it's at most $\beta$. There is at most one
local term per shared slot (single-slot shifts contribute 0), so $\mathcal{L}^*(t) \leq \beta \cdot n_\text{shared}$.
**The normalized global like score** is therefore:

$$
\mathcal{L}^{**}(t) = k \cdot \frac{\mathcal{L}^*(t)}{\beta \cdot n_\text{shared}}
$$

which lies in $[0, k]$. If $n_\text{shared} = 0$ (every shift has a single slot), $\mathcal{L}^{**}(t) = 0$.

The denominator must be a constant. Normalizing each worker by their *own* number of shifts (an average) would break
monotonicity, since an average can decrease when a liked shift is added.

### Workload

Let $w_i \in W$ be a worker with $\mathrm{av}_i > 0$, $t \in \mathbb{N}$, and let $h_t(w_i) \in [0,1]$ be $w_i$'s
**workload** at iteration $t$: the ratio between the hours assigned and the hours available.

$$
h_t(w_i) = \frac{\text{Total hours assigned to } w_i}{\mathrm{av}_i} = \frac{\sum _{s \in A_t(w_i)} |s|}{\mathrm{av}_i}
$$

Since a worker can only be assigned to slots that lie entirely within their availability, and their slots never
overlap, $h_t(w_i) \leq 1$. Naturally, $h_t(w_i)=0$ iff $A_t(w_i) = \emptyset$, and $h_t(w_i) = 1$ iff $w_i$ is
assigned in all of their available hours.
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
number of assigned hours $T = \sum_i \mathrm{av}_i \, h_t(w_i)$ is the same for every complete schedule, and so is
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

#### Normalizing the workload

$h_t(w_i) \leq 1$, but a workload of 1 — working every available hour — is never reachable, since the minimum rest
period forces gaps between shifts. Normalizing by it would compress the workload penalty far below the other
components. Instead, the penalty is normalized by how much each worker could **actually** be packed with work within
the hard constraints (see [ADR 0015](../decisions/0015-normalize-workload-by-packable-maximum.md)).

For every worker $w_i$ with $\mathrm{av}_i > 0$, let $H^{\max}_i$ be the **packable maximum**: the largest total
number of hours $w_i$ could be assigned over any legal set of slots in their domain (calculated in
[the same way as $M_w$](#calculating-the-worst-possible-deficit-m_w), with each slot weighted by its duration). Let
$h^{\max}_i = H^{\max}_i / \mathrm{av}_i$ be the corresponding **packable maximum workload**. Since
$h_t(w_i) \leq h^{\max}_i$ and $\varphi$ is increasing,
$\mathcal{W}(t) \leq \sum_i \mathrm{av}_i \, \varphi(h^{\max}_i)$.
**The normalized global workload function** is therefore:

$$
\mathcal{W}^*(t) = k \cdot \frac{\sum_{i=1}^k \mathrm{av}_i \, \varphi \big( h_t(w_i) \big)}{\sum_{i=1}^k \mathrm{av}_i \, \varphi \big( h^{\max}_i \big)}
$$

which lies in $[0, k]$ for either choice of $\varphi$. If the denominator is 0 (no worker can be assigned anything),
$\mathcal{W}^*(t) = 0$.

The denominator is a constant, calculated once before the search, so this only rescales the workload penalty: it
remains monotone, and it's still minimal exactly when every worker's workload is the same.

The normalized workload never gets near 0 for a complete schedule: the hours that must be worked have a minimum cost,
reached when workloads are equal (by Jensen's inequality, $\left(\sum_i \mathrm{av}_i\right) \varphi(\overline{x})$
before scaling). On the example input, a perfectly fair schedule scores about 4.1 of 9 with $p = 2$. Only differences
between schedules matter to the search, but this is why the workload weight is the largest by default (see
[Parameters](#parameters)).

### Rest

The workload function accounts for fairness in workload, but not for needlessly cramming many shifts for one worker
as close together as possible. That is, for otherwise identical shifts, it doesn't penalize a situation in which
worker A is given $X$ shifts that each start as soon as A's minimum rest period (the hard constraint) is over,
while worker B gets very spread-out shifts.

That said, rest periods shouldn't necessarily all be made as similar as possible, especially in an asynchronous
schedule. An ideal rest period following a 3-hour shift can and should be shorter than one following a 4-hour (or
longer) shift.
A rest period longer than the ideal doesn't need to be penalized either, since the main problem with an overly long
rest period is the risk of it coming at the expense of someone else — and that is already reflected as a shorter
rest for that someone else. If it's possible to give worker X extra rest without it coming at someone's expense, X
should get it.

For these reasons, a fairly simple function suffices: it calculates a **rest deficit** for each rest period of each
worker, sums them up and normalizes the result.

Let $w \in W$ be some worker, and $A_t(w)$ all the slots $w$ is assigned to at iteration $t \in \mathbb{N}$.
Let $A_t(w) = ( s_1, s_2 ,\dots , s_n)$ be ordered by **`DateTimeRange`**, meaning that for every
$s_i , s_j \in A_t(w)$:

$$
s_i < s_j \iff \bigg( [s_i]_\text{start} < [s_j]_\text{start} \bigg) \text{ OR } \bigg( [s_i]_\text{start} = [s_j]_\text{start} \text{ AND } [s_i]_\text{end} < [s_j]_\text{end} \bigg)
$$

(A worker's slots never overlap, so this order is strict and unambiguous.)

For every $s_i \in A_t(w)$, define the **rest period** after $s_i$:

$$
\Delta s_i = \begin{cases} [s_{i+1}]_\text{start} - [s_i]_\text{end} & i \neq n \\ \infty & i=n \end{cases}
$$

and the **rest target** after $s_i$ — the shift's duration times $\gamma$, for some $1 \leq \gamma \in \mathbb{R}$
(the rest factor, a [parameter](#parameters), 3 by default):

$$
r(s_i) = \gamma \cdot |s_i|
$$

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
> * If $s'$ falls between two of $w$'s slots $s_i < s' < s_{i+1}$, the rest after $s_i$ shrinks from
>   $\Delta s_i$ to $[s']_\text{start} - [s_i]_\text{end} < \Delta s_i$, so $d_t(w, s_i)$ can only grow; and $s'$
>   brings a new deficit $d_t(w, s') \geq 0$. (The rest periods around $s'$ add up to *less* than the old one:
>   $\big([s']_\text{start} - [s_i]_\text{end}\big) + \big([s_{i+1}]_\text{start} - [s']_\text{end}\big) = \Delta s_i - |s'|$.)
> * If $s'$ comes after $w$'s last slot, the rest after that slot goes from $\infty$ (no deficit) to a finite value,
>   so its deficit can only grow, and $d_t(w, s') = 0$.
> * If $s'$ comes before $w$'s first slot, it only adds a new deficit $d_t(w, s') \geq 0$.
>
> No other deficit changes, so $\mathcal{R}_t(w)$ never decreases.

Similarly, the **global rest deficit function** at iteration $t$ is:

$$
\mathcal{R}^*_t = \sum _{w \in W} \mathcal{R}_t(w) = \sum _{w \in W} \Bigg( \sum _{s \in A_t(w)} d_t(w,s) \Bigg)
$$

#### Normalizing the rest deficit

The minimum possible deficit for any worker at any slot is 0. Since any two slots assigned to the same worker are at
least $m$ hours apart, $\Delta s \geq m$, so the maximum possible deficit after a slot $s$ is reached when the next
shift starts as soon as the minimum rest period is over:

$$
d_m(s) = \max \big(0, \; r(s) - m \big) = \max \big(0, \; \gamma \cdot |s| - m \big)
$$

If $\gamma \cdot |s| \leq m$, the minimum rest period already meets the rest target and $s$ can never cause a
deficit. So $\gamma$ only has an effect relative to the minimum rest and the shift lengths: with 6 hours' minimum
rest and 3-hour shifts, any $\gamma \leq 2$ turns the rest penalty off entirely.

Normalizing each deficit by $d_m(s)$ isn't very helpful, because the number of rest periods varies; normalization
should instead be relative to *each worker*, whose number is constant for a given schedule.

For every $w \in W$, let $M_w \geq 0$ be **the worst possible deficit** for $w$: the largest value
$\mathcal{R}_t(w)$ could take over any legal set of slots $w$ could be assigned to (calculating $M_w$ is covered in
the next section). **The normalized worker rest deficit function** is
$\frac{1}{M_w} \sum _{s \in A_t(w)} d_t(w,s) = \sum _{s \in A_t(w)} \frac{d_t(w,s)}{M_w}$, which lies between 0
(best case) and 1 (worst case). If $M_w = 0$, $w$ can never have a deficit and the term is defined to be 0.
Therefore, **the normalized global rest deficit function** is:

$$
\mathcal{R}^{**}(t) = \sum _{w \in W} \frac{1}{M_w} \mathcal{R}_t(w) = \sum _{w \in W} \Bigg( \sum_{s \in A_t(w)} \frac{d_t(w,s)}{M_w} \Bigg)
$$

which lies in $[0, k]$.

Normalizing **per worker** is deliberate. Each worker's rest is judged relative to their *own* worst case, just as
their workload is judged relative to their *own* availability. As a result, an hour of deficit weighs more for a
worker whose availability allows only a mild worst case than for a highly available one. This follows the same idea
of fairness as the workload policy, in which unavailable time — leave, other duties, being posted elsewhere — counts
as neither work nor rest.

#### Calculating the worst possible deficit $M_w$

$M_w$ is calculated **exactly**, as the most expensive path in a
[directed acyclic graph](https://en.wikipedia.org/wiki/Directed_acyclic_graph) (DAG)
(see [ADR 0014](../decisions/0014-exact-worst-rest-deficit.md)):

* the nodes are the slots in whose domain $w$ is (after unary pruning);
* there is an edge $s \rightarrow s'$ whenever $w$ could work $s$ and then $s'$ as consecutive shifts, i.e.
  $[s']_\text{start} - [s]_\text{end} \geq m$;
* the edge's weight is the deficit it causes, $\max \big(0, \; \gamma \cdot |s| - ([s']_\text{start} - [s]_\text{end}) \big)$.

Every legal sequence of $w$'s shifts is a path in this graph, and its total deficit is the path's total weight, so
$M_w$ is the weight of the heaviest path. Sorting the slots by time and applying a standard
[longest-path algorithm for DAGs](https://www.geeksforgeeks.org/dsa/find-longest-path-directed-acyclic-graph/)
takes $O(n^2)$ time for $n$ slots, which is cheap at the intended schedule sizes.

The search space can be reduced by looking at **time ranges** rather than distinct slots: in terms of rest deficit,
a shift from $t_1$ to $t_2$ is the same no matter which slot it's spent in.

The packable maximum $H^{\max}_w$ used to normalize the workload is calculated on the same graph, with each slot
weighted by its duration $|s|$ instead of each edge by its deficit.

If these calculations ever become too slow, they can be sped up by limiting the possible first shifts: if a worker's
first shift starts at time $t$ and some shift ends before $t - m$, another shift could be added before it, so the
worst-case (or fullest) sequence **must start with a shift within $m$ hours of the schedule start**.

## Total score for each state

For an iteration $t \in \mathbb{N}$ and three weights $a,b,c \in [0,1]$ such that $a + b + c = 1$ (by default
0.25, 0.5 and 0.25; see [Parameters](#parameters)), the penalty function $\mathcal{P}(t)$ is the weighted sum:

$$
\mathcal{P}(t) = a \cdot \mathcal{L}^{**}(t) + b \cdot \mathcal{W}^*(t) + c \cdot \mathcal{R}^{**}(t)
$$

(The weight $a$ here is unrelated to the parameter $a$ of $\varphi(x) = e^{ax} - 1$.)

Each sub-function is normalized to $[0, k]$, where $k \in \mathbb{N}$ is the number of workers:
$0 \leq g(t) \leq k$ for every $g\in \lbrace \mathcal{L}^{**}, \mathcal{W}^*, \mathcal{R}^{**} \rbrace$.
This means that for every $t \in \mathbb{N}$:

$$
0 \leq \mathcal{P}(t) = a \cdot \mathcal{L}^{**}(t) + b \cdot \mathcal{W}^*(t) + c \cdot \mathcal{R}^{**}(t) \leq ak + bk + ck = (a+b+c)k \underset{a+b+c=1}{=} k  \Rightarrow \underline{0 \leq \mathcal{P}(t) \leq k}
$$

This is fine, as $k$ (the number of workers) stays constant within each run. If normalizing into the range $[0,1]$
is ever needed, it's as simple as $\frac{\mathcal{P}(t)}{k}$.

Each sub-function is monotonically non-decreasing, and the weights are non-negative, so $\mathcal{P}$ is too.

## Parameters

> [!NOTE]
> **Implemented**: [`ScoringParameters`](../reference/api/schedule-input.md#class-scoringparameterslikes_weight-workload_weight-rest_weight-workload_power-rest_factor-neutral_partner)
> and the `scoring` input settings. Decided in
> [ADR 0022](../decisions/0022-scoring-parameters-with-defaults-and-input-overrides.md).

Every parameter has a default, defined once as a named constant in the code, and can be overridden in the optional
`scoring` section of the input's settings (see [Input format](../reference/input-format.md#scoring)).

| Parameter | Symbol | Default | Input field | Allowed values |
|-----------|--------|---------|-------------|----------------|
| Weights of likes, workload and rest | $a$, $b$, $c$ | 0.25, 0.5, 0.25 | `weights: {likes, workload, rest}` | at least 0, not all 0; divided by their sum |
| Workload power | $p$ | 2 | `workload_power` | a whole number, at least 2 |
| Rest factor | $\gamma$ | 3 | `rest_factor` | at least 1 |
| Neutral partner, relative to a disliked one | $\alpha / \beta$ | 1/3 | `neutral_partner` | more than 0, less than 1 |

What the defaults mean, on the example input (9 workers, 72 hours):

| Change to a schedule | Penalty change, before weights | After default weights |
|----------------------|-------------------------------|-----------------------|
| Moving one 3-hour shift from the busiest worker to the least busy | about −0.23 | about −0.11 |
| One worker paired with someone they dislike instead of a neutral partner | about +0.23 | about +0.06 |
| One hour of rest below target | about +0.05 | about +0.01 |

Scores are floating-point numbers. Each one is computed from scratch, with sums always taken in the same order, so
the same state always gets exactly the same score, and since every operation involved is monotone under rounding,
a state never scores lower than its parent. Exactness would only matter if scores were updated incrementally.

Still open: whether scores can practically be updated incrementally from their previous values (see
[Future work](future-work.md#incremental-scoring)); until then, they're computed from scratch.

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
   so the weights' meaning depended on the schedule's size. It's now divided by its maximum,
   $\beta \cdot n_\text{shared}$, and scaled to $[0,k]$.
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
   [ADR 0015](../decisions/0015-normalize-workload-by-packable-maximum.md).
