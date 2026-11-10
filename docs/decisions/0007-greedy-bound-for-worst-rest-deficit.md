# 0007. Bound the worst rest deficit greedily

**Status:** Superseded by [0014](0014-exact-worst-rest-deficit.md).

## Context

The rest penalty is normalized per worker by $M_w$, the worst possible rest deficit for that worker. Calculating
$M_w$ exactly means finding the most expensive path in a directed acyclic graph of the worker's possible slots.

## Decision

Use a *good enough* upper bound for $M_w$, found with a greedy algorithm, rather than calculating it exactly. Two
greedy methods are considered — a simple one (repeatedly take the earliest-ending non-conflicting slot) and a tuned
one (build a greedy chain from each plausible starting slot and take the worst). The choice between them is still
open. See [Scoring](../explanation/scoring.md#calculating-the-worst-possible-deficit-m_w).

## Consequences

* Much simpler to implement than an exact longest-path calculation.
* The normalized rest penalty may not reach exactly 1 in the worst case; it's assumed this is good enough.
