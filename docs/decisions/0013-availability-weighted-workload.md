# 0013. Weight the workload penalty by availability

**Status:** Accepted. Normalization amended by [0015](0015-normalize-workload-by-packable-maximum.md) (itself superseded by [0032](0032-flat-penalty-parts.md)); the load amended by [0026](0026-workload-counts-shifts-and-hours.md) (shifts count as well as hours). Amends the penalty formula of [0006](0006-convex-function-for-workload-fairness.md).

## Context

TinyScheg's workload policy is that workloads — each worker's assigned hours as a share of their *own* available
hours, $h_i = H_i / \mathrm{av}_i$ — should be as equal as possible. [ADR 0006](0006-convex-function-for-workload-fairness.md)
chose the penalty $\sum_i \varphi(h_i)$ for a convex, increasing $\varphi$, relying on Jensen's inequality: the sum
is minimal when all $h_i$ are equal.

That argument only holds when $\sum_i h_i$ is fixed. What's actually fixed in a complete schedule is the total
number of hours, $T = \sum_i \mathrm{av}_i \, h_i$, since every slot must be filled. When availabilities differ, the
unweighted sum is minimized at unequal workloads: solving for $\varphi(x) = x^p$ gives
$H_i \propto \mathrm{av}_i^{\,p/(p-1)}$, so the most available workers get disproportionately many hours.

For example, with two workers available for 10 and 40 hours sharing 10 hours of shifts, equal workloads mean 2 and 8
hours ($h = 0.2$ each). The unweighted penalty with $p = 2$ is instead minimized at about 0.59 and 9.41 hours
($h \approx 0.06$ and $0.24$).

## Decision

Weight each worker's term by their availability:

$$
\mathcal{W} = \sum_i \mathrm{av}_i \, \varphi(h_i)
\qquad
\mathcal{W}^* = k \cdot \frac{\sum_i \mathrm{av}_i \, \varphi(h_i)}{\varphi(1) \cdot \sum_i \mathrm{av}_i}
$$

By the weighted Jensen inequality, $\sum_i \mathrm{av}_i\,\varphi(h_i) \geq \left(\sum_i \mathrm{av}_i\right)\varphi(T / \sum_i \mathrm{av}_i)$,
and the right-hand side is the same for every complete schedule. The penalty is therefore minimal exactly when all
workloads are equal, as the policy requires. Workers with no availability in the schedule period are left out.

Everything else in [ADR 0006](0006-convex-function-for-workload-fairness.md) still holds: a convex, increasing
$\varphi$, with $x^p$ and $e^{ax} - 1$ as candidates.

## Consequences

* The penalty now matches the workload policy for any mix of availabilities.
* The penalty remains monotone and convex. The marginal cost of assigning $|s|$ more hours to a worker is roughly
  $|s| \cdot \varphi'(h_i)$: it depends only on the worker's current workload, not on their availability.
* $\mathcal{W}^*$ is normalized to $[0, k]$ for either choice of $\varphi$.
