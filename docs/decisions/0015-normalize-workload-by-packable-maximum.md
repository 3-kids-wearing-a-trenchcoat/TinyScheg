# 0015. Normalize workload by each worker's packable maximum

**Status:** Accepted. Amends the normalization of [0013](0013-availability-weighted-workload.md).

## Context

[ADR 0013](0013-availability-weighted-workload.md) normalized the workload penalty by its theoretical maximum, a
workload of 1 for every worker: working every available hour. That's never reachable, because the minimum rest
period forces gaps between a worker's shifts. In practice workloads stay well below it (on random test instances, the
most a worker could be packed with was a workload of about 0.5), so with $\varphi(x) = x^2$ the workload penalty used
only about a quarter of its range or less.

Measured on random instances, the difference in normalized workload penalty between the best and worst of a sample
of complete schedules was about 0.026 per worker (median), compared to 0.375 for rest. The weights would have had to
make up for a scale difference that varies from instance to instance.

## Decision

Normalize the workload penalty by how much each worker could **actually** be packed with work within the hard
constraints. For each worker $w_i$, the **packable maximum** $H^{\max}_i$ is the largest number of hours $w_i$ could
be assigned over any legal set of slots in their domain, calculated exactly as the heaviest path in the same graph
used for the worst rest deficit ([ADR 0014](0014-exact-worst-rest-deficit.md)), with slots weighted by duration.
With $h^{\max}_i = H^{\max}_i / \mathrm{av}_i$:

$$
\mathcal{W}^* = k \cdot \frac{\sum_i \mathrm{av}_i \, \varphi(h_i)}{\sum_i \mathrm{av}_i \, \varphi(h^{\max}_i)}
$$

See [Scoring](../explanation/scoring.md#normalizing-the-workload).

## Consequences

* The workload penalty uses a much larger part of its range: on the same random instances, the median best-to-worst
  difference grew from about 0.026 to about 0.10 per worker. The weights can then balance it against the other
  components more consistently across instances.
* The denominator is a constant calculated once before the search, so the penalty remains monotone, path-independent
  and minimal exactly when all workloads are equal.
* $\mathcal{W}^*$ still lies in $[0, k]$, since no worker's workload can exceed their packable maximum.
* Calculating $H^{\max}_i$ costs the same as calculating $M_w$, once per worker before the search.
