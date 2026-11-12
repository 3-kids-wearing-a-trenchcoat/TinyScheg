# 0026. Workload counts shifts as well as hours

**Status:** Accepted.

## Context

The workload penalty ([ADR 0013](0013-availability-weighted-workload.md), [ADR 0021](0021-power-function-for-workload-fairness.md))
compares the **hours** each worker is given, relative to their availability. In asymmetric schedules, with shifts of
different lengths and short dangling shifts, two workers can be even in hours but not in shifts: one does three
short shifts (5 hours in all), the other one long one (6 hours). The penalty sees nothing to fix.

Workers see it differently. Every shift is another time to show up, hand over and break up their day or night, so
three shifts weigh more than one, whatever their hours. After the search speedups of 2026-11-12 let looser
benchmark inputs finish, every one of the 22 distinct main complaints with an easy fix in the
[tuning](../explanation/tuning.md) baseline was such a load complaint: 3 shifts against 1, at about the same hours.
No parameter could fix them, since the penalty measured only hours. Asked whether it's the shifts or the hours that
matter, the user answered: both, in some proportion.

## Decision

Each slot's **load** blends its hours with one average slot, and the workload penalty measures load instead of
hours:

$$
\ell(s) = (1 - \sigma) \, |s| + \sigma \, \bar{L}
$$

where $|s|$ is the slot's length in hours, $\bar{L}$ the mean length of the schedule's slots (each schedule sets
its own norm, as the [schedule audit](../explanation/schedule-audit.md) does), and $\sigma \in [0, 1]$ the new
**shift share** parameter, by default 0.5. With $\sigma = 0$ only hours count, as before; with $\sigma = 1$ every
shift counts the same.

Everything else about workload stays: $h_t(w_i)$ is the assigned load over $\mathrm{av}_i$, the packable maximum
$H^{\max}$ is the most load over any legal set of slots, and the lower bound spreads the remaining load. Rest still
uses real hours.

Rejected: a separate shift-count term with its own weight, next to likes, workload and rest. It would keep hours and
shifts apart, but needs its own normalization and lower bound, and adds a weight that interacts with the other three.

## Consequences

* Every property the workload penalty relies on still holds: each slot adds a positive load, so the penalty is
  monotone; the total load of a complete schedule is fixed (it equals the total hours, since the blend keeps the
  mean), so Jensen's inequality still makes equal workloads the minimum; and the lower bound is still valid.
* $h_t(w_i)$ can exceed 1 for a worker with many short shifts, so the bound $h_t(w_i) \leq 1$ no longer holds; the
  normalization by the packable maximum still keeps the penalty in $[0, k]$.
* The default changes the best schedules of inputs with shifts of different lengths; inputs where every slot has
  the same length are unaffected, since then every slot's load is its hours.
* $\sigma$ is set in the input's `scoring` section as `shift_share`, like the other parameters
  ([ADR 0022](0022-scoring-parameters-with-defaults-and-input-overrides.md)); its default is for tuning to confirm.
