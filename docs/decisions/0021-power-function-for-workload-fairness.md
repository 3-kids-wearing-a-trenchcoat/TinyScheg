# 0021. Use a whole-number power for workload fairness

**Status:** Accepted. Amends the choice of $\varphi$ left open by [0006](0006-convex-function-for-workload-fairness.md).

## Context

[ADR 0006](0006-convex-function-for-workload-fairness.md) chose a convex, increasing function $\varphi$ for the
workload penalty and left open whether it's $\varphi(x) = x^p$ ($p > 1$) or $\varphi(x) = e^{ax} - 1$ ($a > 0$).

On the example input, with each penalty normalized as in [Scoring](../explanation/scoring.md), moving one 3-hour
shift from the busiest worker to the least busy reduced the workload penalty by about 0.23 with $x^2$, 0.34 with $x^3$
and 0.11–0.19 with $e^{ax} - 1$ for $a$ between 3 and 5. The exponential pulled *less* towards fairness at the same
scale. It also can't be computed exactly, while [ADR 0012](0012-deterministic-path-independent-scoring.md) favours
exact arithmetic should scores ever be updated incrementally.

## Decision

$\varphi(x) = x^p$, with $p$ a whole number of at least 2. The default is $p = 2$.

With $p = 2$, minimizing $\sum_i \mathrm{av}_i \, h_t(w_i)^2$ is the same as minimizing the availability-weighted
variance of the workloads, since the weighted mean workload is the same for every complete schedule. Over- and
under-loaded workers are treated alike. Larger $p$ leans harder on the most loaded workers.

$p$ is a scoring parameter like the others, with its default as a named constant, and can be set in the input
([ADR 0022](0022-scoring-parameters-with-defaults-and-input-overrides.md)).

## Consequences

* The workload penalty has a plain meaning: the spread of workloads.
* Penalties can be computed exactly (whole-number powers of rationals), which keeps incremental scoring exact if it's
  ever added.
* The exponential option is dropped; a different curve would need a new ADR.
