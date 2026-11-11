# 0006. Use a convex function for workload fairness

**Status:** Accepted. Penalty formula amended by [0013](0013-availability-weighted-workload.md); the choice of
$\varphi$ made by [0021](0021-power-function-for-workload-fairness.md).

## Context

What matters for workload isn't each worker's absolute workload but that workloads are as equal as possible. A
fairness penalty is needed that doesn't depend on knowing the average workload in advance, which isn't known during
the search.

## Decision

Apply a **convex, monotonically increasing** function $\varphi$ to each worker's workload ratio $h_t(w)$ and sum the
results: $\sum_i \varphi(h_t(w_i))$. By Jensen's inequality, this sum is minimal exactly when all workloads are
equal, without needing to know the average.

Two candidates are considered: $\varphi(x) = x^p$ with $p > 1$, and $\varphi(x) = e^{ax} - 1$ with $a > 0$. The
choice between them is still open.

## Consequences

* The higher a worker's workload, the higher the penalty for giving them another assignment, so the penalty both
  keeps workloads equal and minimizes assignments.
* Since $\varphi$ is increasing, the penalty is monotone as assignments are added.
* The choice of $\varphi$ and its parameter controls how harshly unequal workloads are penalized.
