# Scoring

> [!WARNING]
> **Not yet implemented.** This page is the specification for TinyScheg's scoring. None of it exists in code yet.
> See [ADR 0005](../decisions/0005-weighted-sum-of-normalized-penalties.md),
> [ADR 0006](../decisions/0006-convex-function-for-workload-fairness.md) and
> [ADR 0007](../decisions/0007-greedy-bound-for-worst-rest-deficit.md).

## General idea

Each schedule state — **including incomplete schedules** — has a score. Scores are monotonically non-decreasing
*penalties*: each state's penalty is greater than or equal to the penalty of its parent state.

The penalty is a sum of the penalties given by each worker, which is analogous to each worker saying how much they
*dislike* the schedule as it currently stands. This is done by a `Scorer` class: each `Worker` holds a `Scorer`
containing only the information and methods needed to calculate that worker's penalty.

The penalty is what makes the [pocket](search-algorithm.md#branch-and-bound-the-pocket) work: once a complete,
legal schedule has been found, any partial schedule whose penalty is already higher can be pruned, since its
penalty can only grow.

## Calculations

Each *criterion* (likes/dislikes, workload, rest) has its own penalty function. Each function is **normalized**, and
their **weighted sum** is the total penalty.

Ideally, each score would be derived from its previous value to make these calculations more efficient, but how
practical that is remains to be seen. (At least *undoing* an action and its influence on a score can be done
through the [`Trail`](search-algorithm.md#trail).)
A proper score must be produced for every single state, since its absolute value is compared with the pocket's —
scores can't be calculated lazily.

### Definitions

* $W = \lbrace w_1, w_2, \dots , w_k \rbrace$ is the set of all workers ($k \in \mathbb{N}$ is the total number of
  workers).
* For every worker $w_i \in W$, let $L_i \subset W$ be the group of workers that $w_i$ likes.
* For every worker $w_i \in W$, let $H_i \subset W$ be the group of workers that $w_i$ dislikes. It is assumed that
  $\forall i \in [1,k] \quad L_i \cap H_i = \emptyset$.
* $S = \lbrace s_1, s_2, \dots ,s_n \rbrace$ is the set of all slots ($n\in \mathbb{N}$ is the total number of slots).
* For every slot $s_i \in S$, let $D_i \subseteq W$ be **the domain** of $s_i$.
* The notation $s_i \sim s_j$ means that $s_i$ and $s_j$ **belong to the same shift**.
  * For every slot $s_i \in S$, the set $\mathcal{S}(s_i) = \lbrace s_j \in S \mid s_i \sim s_j \rbrace$ is the shift
    $s_i$ belongs to.
    Notice that $s_i \sim s_i \Leftrightarrow s_i \in \mathcal{S}(s_i)$, that if $s_j \sim s_i$ then
    $\mathcal{S}(s_i) = \mathcal{S}(s_j)$, and that for every $s_i, s_j \in S$ such that $s_i \nsim s_j$,
    $\mathcal{S}(s_i) \cap \mathcal{S}(s_j) = \emptyset$.
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

### Likes/dislikes

Let $l_i(x)$ be the **like function** for worker $w_i$:

$$
l_i(x) = \begin{cases} 0 & x \in L_i \\ \alpha & x \notin L_i \cup H_i \\ \beta & x \in H_i \end{cases}
$$

such that $\alpha ,\beta \in \mathbb{R}$ and $0 < \alpha < \beta$.
That is, liked workers produce no penalty, workers who are neither liked nor disliked produce a relatively small
penalty, and disliked workers produce a bigger penalty.

At iteration $t \in \mathbb{N}$, the **local like function** $\mathcal{L}_t:W \times S \rightarrow \mathbb{R}$ is
($| \cdot |$ denoting the **size** of $\cdot$):

$$
\mathcal{L}_t(w_i, s_i) = \frac{1}{| \mathcal{S}(s_i) | - 1} \cdot \sum_{w \in A_t \big( \mathcal{S}(s_i) \big)} l_i(w) = \sum_{w \in A_t \big(\mathcal{S}(s_i) \big)} \frac{l_i(w)}{| \mathcal{S}(s_i) | - 1}
$$

Or less formally: $\mathcal{L}_t (w_i, s_i)$ is **the sum of the like function of $w_i$ over all workers assigned to
slots that share a shift with $s_i$, averaged over the number of other slots in that shift**.
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

The highest possible penalty for any worker at any shift is $\beta$. Since $\mathcal{L}^*(t)$ is a sum of such
penalties, **the normalized global like score** is:

$$
\mathcal{L}^{**}(t) = \frac{\mathcal{L}^*(t)}{\beta} = \sum_{w \in W} \frac{\mathcal{L}_t(w)}{\beta}
$$

### Workload

Let $w\in W$ be a worker, $t \in \mathbb{N}$, and let $h_t(w) \in [0,1]$ be $w$'s **workload** at iteration $t$:
the ratio between the hours assigned and the total hours available.

$$
h_t(w) = \frac{\text{Total hours assigned to } w}{\text{Total hours in which } w \text{ is available}} = \frac{\sum _{s \in A_t(w)} \text{duration of } s}{\text{Total hours in which } w \text{ is available}} = \sum _{s \in A_t(w)} \frac{ \text{duration of } s}{\text{Total hours in which } w \text{ is available}}
$$

Naturally, $h_t(w)=0$ iff $A_t(w) = \emptyset$, and $h_t(w) = 1$ iff $w$ is assigned in all of $w$'s available
hours.
The absolute workload of each worker doesn't matter; what matters is that it's as **fair** as possible, meaning
workloads should be as close to one another as possible. The workload penalty function is therefore built from a
function $\varphi$, as follows.

#### The function $\varphi$ and Jensen's inequality

We use a **convex, monotonically increasing** function $\varphi :\mathbb{R} \rightarrow \mathbb{R}$ and take
advantage of [Jensen's inequality](https://en.wikipedia.org/wiki/Jensen%27s_inequality#Finite_form).

**Jensen's inequality** states (in the special case relevant here) that for a real convex function $\varphi$ and
numbers $x_1,\dots, x_n$ in its domain:

$$
\varphi \left( \frac{\sum x_i}{n} \right) \leq \frac{\sum \varphi (x_i)}{n}
$$

Let $\overline{x} = \frac{1}{n} \sum_{i=1}^n x_i$, the average of $\lbrace x_1, \dots ,x_n \rbrace$. Then:

$$
\varphi \left( \frac{\sum x_i}{n} \right) = \varphi (\overline{x}) \leq \frac{\sum \varphi (x_i)}{n} = \frac{1}{n} \sum \varphi (x_i) \quad \underset{\cdot n}{\rightarrow} \quad n \varphi(\overline{x}) \leq \sum_{i=1}^n \varphi (x_i)
$$

This means that if $\sum _{i=1}^n \varphi (x_i)$ is the total penalty function, its **minimum** is exactly when
$x_1 = \dots = x_n = \overline{x}$. In other words, **this penalty function is minimal when all values are the
same**, which is what we're looking for.
The advantage of this function is that we don't need to know (or even guess) what the average value is.

We can also see that for every $a \neq b$, $\varphi (a) + \varphi (b) \geq 2 \varphi \left( \frac{a+b}{2} \right)$,
with equality iff $a=b$.
So by increasing the smaller value by $0 < c \in \mathbb{R}$ such that $|a-b| > |a+c-b|$ (making $a$ "more similar"
to $b$), we also approach the local minimum without requiring backtracking.
That is, as long as $\varphi$ is convex and monotonically increasing, each step that makes $x_1 ,\dots ,x_n$ "more
similar" also approaches the desirable local minimum.

Naturally, we choose $x_i$ to be $h_t (w_i)$, so the total workload penalty function at iteration $t \in \mathbb{N}$
is $\sum _{i=1}^k \varphi (h_t(w_i))$.

There are two "low-hanging fruit" options for $\varphi$:

1. $\varphi (x) = x^p$ where $p>1$
2. $\varphi (x) = e^{ax} - 1$ where $a > 0$

Generally speaking, $x^p$ and $e^{ax} -1$ penalize harder as $p$ and $a$ increase respectively, and $e^{ax} - 1$ is
*much stricter* (penalizes harder) than $x^p$.
This works for two main reasons. The first, as mentioned, is that there is a single minimum, when
$x_1 = \dots = x_n$. The second is that for any $x_1, \dots ,x_n$, the value increase that yields the lowest penalty
is the one that makes the values overall "closer" to one another.
In TinyScheg, this means that the higher a worker's workload, the higher the penalty for giving them another
assignment, so this penalty function simultaneously seeks to **keep workload equal** and to **minimize
assignments**.

![Plot of x^p and e^(ax) - 1 on the range [0, 1]](../images/workload-phi-functions.png)

> Pictured: $x^p$ (in purple) and $e^{ax} -1$ (in red) on the range $[0,1]$, with $p$ and $a$ chosen to almost
> intersect at $x=1$. Increasing $p$ "moves the midpoint" to the right, whereas increasing $a$ makes the ascent much
> sharper.

**If we choose** $\varphi (x) = x^p$, the global function for each iteration is:

$$
\sum _{i=1}^k \varphi \left( h_t(w_i) \right) = \sum _{i=1}^k \left( h_t(w_i) \right) ^p = \sum _{i=1}^k \frac{\left( \text{hours assigned to } w_i \text{ in iteration } t \right)^p}{\left( \text{total availability of } w_i \right)^p} = \sum _{i=1}^k \frac{\left( \sum _{s \in A_t(w_i)} \text{duration of } s \right)^p}{\left( \text{total availability of } w_i \right)^p}
$$

and its normalized form is simply $\frac{1}{k} \sum _{i=1}^k \varphi \left( h_t(w_i) \right)$.

**If we choose** $\varphi(x) = e^{ax}-1$, the global function for each iteration is:

$$
\sum _{i=1}^k \varphi \left( h_t(w_i) \right) = \sum_{i=1}^k \left( e^{a \cdot h_t(w_i)} - 1 \right) = \sum _{i=1}^k \bigg( \exp \big( a\cdot h_t(w_i) \big) \bigg) - k = \sum _{i=1}^k \left( \exp \left( a \cdot \frac{\sum _{s \in A_t(w_i)} \text{duration of } s}{\text{total availability of }w_i} \right) \right) -k
$$

and its **normalized form** is $\frac{1}{e^a - 1} \sum _{i=1}^k \varphi \left( h_t(w_i) \right)$.

We denote the global workload function by $\mathcal{W}(t) = \sum_{i=1}^k \varphi (h_t(w_i))$ and its normalized form
by $\mathcal{W}^*(t)$.

### Rest

The workload function accounts for fairness in workload, but not for needlessly cramming many shifts for one worker
as close together as possible. That is, for otherwise identical shifts, it doesn't penalize a situation in which
worker A is given $X$ shifts that each start as soon as A's minimum rest period (the hard constraint) is over,
while worker B gets very spread-out shifts.

That said, rest periods shouldn't necessarily all be made as similar as possible, especially in an asynchronous
schedule. An ideal rest period following a 3-hour shift can and should be shorter than one following a 4-hour (or
longer) shift.
A rest period longer than the ideal doesn't need to be penalized either, since the main problem with an overly long
rest period is the risk of it coming at the expense of someone else. If it's possible to give worker X extra rest
without it coming at someone's expense, X should get it.

For these reasons, a fairly simple function suffices: it calculates a **rest deficit** for each rest period of each
worker, sums them up and normalizes the result.

Let $w \in W$ be some worker, and $A_t(w)$ all the slots $w$ is assigned to at iteration $t \in \mathbb{N}$.
Let $A_t(w) = ( s_1, s_2 ,\dots , s_n)$ be ordered by **`DateTimeRange`**, meaning that for every
$s_i , s_j \in A_t(w)$:

$$
s_i < s_j \iff \bigg( [s_i]_\text{start} < [s_j]_\text{start} \bigg) \text{ OR } \bigg( [s_i]_\text{start} = [s_j]_\text{start} \text{ AND } [s_i]_\text{end} < [s_j]_\text{end} \bigg)
$$

For every $s_i \in A_t(w)$, define the **rest period** for $s_i$:

$$
\Delta s_i = \begin{cases} [s_{i+1}]_\text{start} - [s_i]_\text{end} & i \neq n \\ \infty & i=n \end{cases}
$$

and the **rest target** for $s_i$ (shift length times $\gamma$), for some $1 \leq \gamma \in \mathbb{R}$:

$$
r(s_i) = \gamma \bigg( [s_{i+1}]_\text{start} - [s_i]_\text{end} \bigg)
$$

(All time periods are in hours.)

For every $w \in W$ and $s \in A_t(w)$, the **rest deficit function** $d_t(w,s)$ is:

$$
d_t(w,s) = \max \bigg( 0, \; r(s) - \Delta s \bigg)
$$

That is, $d_t(w,s)$ is how many hours **below** the rest target worker $w$ actually rested after shift $s$.
If $w$'s rest period after $s$ was equal to or greater than the rest target, $d_t(w,s) = 0$.

The **worker rest deficit function** at iteration $t$ is:

$$
\mathcal{R}_t(w) = \sum _{s \in A_t(w)} d_t(w,s)
$$

That is, the sum of the rest deficits for each shift $w$ is assigned to at iteration $t$.

> Monotonicity is evident from the fact that for sorted shifts $s_1 < s_2 < s_3$,
> $\Delta(s_1, s_3) < \begin{matrix} \Delta(s_1, s_2) \\ \Delta(s_2, s_3) \end{matrix} < \Delta(s_1,s_2) + \Delta (s_2,s_3)$.
> That is, the deficit can only increase for each shift, and therefore so can the sum of these deficits.

Similarly, the **global rest deficit function** at iteration $t$ is:

$$
\mathcal{R}^*_t = \sum _{w \in W} \mathcal{R}_t(w) = \sum _{w \in W} \Bigg( \sum _{s \in A_t(w)} d_t(w,s) \Bigg)
$$

#### Normalization

The maximum possible deficit for a slot is achieved by assigning a worker to a post as soon as possible, i.e. as
soon as that worker's minimum rest period (the hard constraint) is over. The minimum possible deficit for any
worker at any slot is, of course, 0.

Let $m \in \mathbb{R}^+$ be **the minimum rest period** as defined in the hard constraints.
For any slot $s \in S$, the maximum possible rest deficit (with the minimal rest period) is:

$$
d_m(s) = r(s) - \Delta s \underset{\Delta s = m}{=} r(s) - m = \gamma \bigg( [s_{i+1}]_\text{start} - [s_i]_\text{end} \bigg) - m = \gamma \cdot [s]_\text{duration in hours} -m
$$

So the normalized form of the rest deficit function would be
$d_t^* (w,s) = \frac{d_t(w,s)}{d_m(s)} = \max \big( 0, \; \frac{r(s)-\Delta s}{r(s) - m} \big)$.
This isn't very helpful because the number of rest periods varies; normalization should instead be relative to
*each worker*, whose number is constant for a given schedule.

For every $w \in W$, let $0 < M_w \in \mathbb{R}$ be **the worst possible deficit** for $w$ (calculating $M_w$ is
covered in the next section). **The normalized worker rest deficit function** is
$\frac{1}{M_w} \sum _{s \in A_t(w)} d_t(w,s) = \sum _{s \in A_t(w)} \frac{d_t(w,s)}{M_w}$, which keeps it between 0
(best case) and 1 (worst case).
Therefore, **the normalized global rest deficit function** is:

$$
\mathcal{R}^{**}(t) = \sum _{w \in W} \frac{1}{M_w} \mathcal{R}_t(w) = \sum _{w \in W} \Bigg( \sum_{s \in A_t(w)} \frac{d_t(w,s)}{M_w} \Bigg)
$$

#### Calculating the worst possible deficit $M_w$

There are two ways to do this: calculate $M_w$ precisely by finding the most expensive path in a
[directed acyclic graph](https://en.wikipedia.org/wiki/Directed_acyclic_graph) (DAG), using something like a
[longest-path algorithm for DAGs](https://www.geeksforgeeks.org/dsa/find-longest-path-directed-acyclic-graph/), or
find a *good enough* upper bound and use it as $M_w$.

TinyScheg uses an upper bound, found with a simple greedy algorithm. There are two options:

* **Simple:** sort the slots by time and iteratively take the earliest-ending slot that doesn't conflict with what
  has been taken so far. This can be sped up by using each worker's domain set to remove irrelevant slots.
* **Tuned:** similar to the simple option, a little more expensive but still much cheaper than the DAG, and
  (*usually*) producing a tighter upper bound. For every possible beginning slot, a chain is built by greedily
  choosing, at each step, the next slot that maximizes the rest penalty. This produces several chains, each with its
  own rest penalty, and the maximum of those is $M_w$.
  The worst-case complexity of this method is $O(n^2)$, but in practice it can be made much quicker by limiting the
  set of possible beginning slots:
  * Let $m\in \mathbb{R}^+$ be the minimum rest period. Suppose a worker's first shift in the schedule *starts* at
    time $t$. If some shift *ends* earlier than $t - m$, at least one more shift could be crammed into this
    worker's schedule. So the worst-case chain **must start with a shift within $m$ hours of the schedule start**.
  * The search space can be reduced further by looking at **time ranges** rather than distinct slots: in terms of
    rest deficit, a shift from $t_1$ to $t_2$ is the same no matter which slot it's spent in.

## Total score for each state

For an iteration $t \in \mathbb{N}$ and three weights $a,b,c \in [0,1]$ such that $a + b + c = 1$, the penalty
function $\mathcal{P}(t)$ is the weighted sum:

$$
\mathcal{P}(t) = a \cdot \mathcal{L}^{**}(t) + b \cdot \mathcal{W}^*(t) + c \cdot \mathcal{R}^{**}(t)
$$

Each sub-function normalizes its results per worker, so with $k \in \mathbb{N}$ workers,
$0 \leq g(t) \leq k$ for every $g\in \lbrace \mathcal{L}^{**}, \mathcal{W}^*, \mathcal{R}^{**} \rbrace$.
This means that for every $t \in \mathbb{N}$:

$$
0 \leq \mathcal{P}(t) = a \cdot \mathcal{L}^{**}(t) + b \cdot \mathcal{W}^*(t) + c \cdot \mathcal{R}^{**}(t) \leq ak + bk + ck = (a+b+c)k \underset{a+b+c=1}{=} k  \Rightarrow \underline{0 \leq \mathcal{P}(t) \leq k}
$$

This is fine, as $k$ (the number of workers) stays constant within each run. If normalizing into the range $[0,1]$
is ever needed, it's as simple as $\frac{\mathcal{P}(t)}{k}$.

## Open questions

* Which function to use for $\varphi$: $x^p$ or $e^{ax} - 1$.
* Which greedy method to use for $M_w$: simple or tuned.
* The values of the parameters $\alpha$, $\beta$, $\gamma$, $p$ or $a$, and of the weights $a$, $b$, $c$ — and
  whether they're fixed or configurable through the input.
* Whether scores can practically be updated incrementally from their previous values.
