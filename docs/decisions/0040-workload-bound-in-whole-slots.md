# 0040. A workload bound in whole slots

**Status:** Accepted. Amends [0024](0024-cheapest-first-value-order-and-workload-bound.md) (the lower bound on
workload).

## Context

Raising the workload weight to the new defaults ([ADR 0039](0039-default-weights-from-the-users-trade-offs.md)) made
branch and bound 3–7 times slower. `confirm_01`, a 24-hour benchmark input, took 6915 s and 982 million nodes to
prove its best schedule, which it had found after 266 s. The search spent almost all of that time proving that
nothing better existed.

The workload part of the lower bound ([ADR 0024](0024-cheapest-first-value-order-and-workload-bound.md)) spreads the
load of the unfilled slots as if it could be split finely ("water-filling"). A measurement on 2026-11-14 blanked
random slots of good schedules and compared that bound with the true lowest workload of their completions. It also
checked the bound's other relaxations one at a time:
* **Whole slots:** 0.4–1.1 workload units of the gap, about 2 on `confirm_01`. That's about 1.2 in the total
  penalty, where the best schedules lie within 0.03 of each other. This is where almost all of the gap was.
* **Who can take which slot (roles, domains):** about 0.
* **Rest between the blanked slots:** about 0.

The workload weight multiplies this gap, so the heavier weight left far more branches unpruned.

## Decision

The workload bound is the higher of water-filling and a **bound in whole slots**, which hands each unfilled slot's
load whole to one worker. It's a Lagrangian relaxation of "all the remaining load $R$ is handed out". For any
completion that gives each worker $w$ an extra load $z_w$, the $z_w$ adding up to $R$, and for any number $\mu$:

$$\sum_w f_w(z_w) = \mu R + \sum_w \bigl(f_w(z_w) - \mu z_w\bigr) \ge \mu R + \sum_w \min_{z \in T_w} \bigl(f_w(z) - \mu z\bigr) = LB(\mu)$$

Here $f_w(z) = \mathrm{av}_w \cdot ((x_w + z) / \mathrm{av}_w)^p$ is the worker's workload term with $x_w$ already
assigned, and $T_w$ is any set holding every extra load they could get. So $LB(\mu)$ is a lower bound for every $\mu$,
and each worker's minimum is found on its own.

* **The sets $T_w$:** whole numbers of the remaining slots of each load, no more of each load than remain, at most
  $n_w = \lfloor \mathrm{cap}_w / u \rfloor$ slots in all ($u$ the smallest remaining load), and at most
  $\mathrm{cap}_w$ in all ($\mathrm{cap}_w$ the load of the unfilled slots in the worker's domains).
  * Exact combinations, while there are at most `MAX_LOAD_COMBINATIONS` (64) of them. The counts of every load but
    the most frequent are listed, and the most frequent load's count is the whole number on either side of the ideal.
  * Beyond that, the wider intervals $\lbrace 0 \rbrace \cup [u, L] \cup [2u, 2L] \cup \dots$, with $L$ the largest
    remaining load.
* **The search for $\mu$:**
  * It starts at the water level's marginal cost.
  * It brackets the best $\mu$ in at most `MU_STEPS` (3) steps, each moving $\mu$ by `MU_GROWTH` (1.5) times, then
    halves the bracket `MU_STEPS` times.
  * It's guided by how much load the per-worker minimizers hand out compared with $R$, and stops early when they hand
    out exactly $R$.
  * Every value tried is valid, so fewer steps only loosen the bound.
* **Rounding:** the bound is lowered by a relative `ROUNDING_MARGIN` ($10^{-9}$), far more than its rounding error.
  So it never rises above a completion, and a branch it prunes holds nothing that could even tie the pocket.
* **One shared computation:** the from-scratch bound and the incremental one
  ([ADR 0027](0027-incremental-scoring-for-steering.md)) call the same function (`workload_bound_total`). The
  incremental scorer keeps a count of the unfilled slots of each load; the scoring constants group the slots by load
  (`load_classes`).
* **Where it doesn't apply:** if a worker with no availability could take load. Their term isn't counted, so load
  they took would be free. The bound then falls back to water-filling.

## Consequences

* **The same results.** A valid bound prunes only branches that can't beat the pocket, and with the margin, none that
  could even tie it. So the search finds exactly the same schedule as before, only sooner.
  * Tests compare the bound with brute force on random cases: exact and interval sets, powers 2 and 3. It's never
    above the best whole-slot completion, and often above water-filling.
  * The search gives the same result with and without it on the small brute-force inputs.
  * On every benchmark input, alone and as day 2, the schedules and penalties are identical to the recorded ones.
* **Much faster** (2026-11-15, PyPy, 8 runs at a time):

  | Input | Nodes before | Nodes after | Seconds before | Seconds after |
  |---|---|---|---|---|
  | `confirm_01` | 982 M | 13.1 M | 6915 | 264 |
  | `sweep_06` | 79.6 M | 2.58 M | 478 | 66 |
  | `sweep_02` | 26.2 M | 2.81 M | 455 | 69 |
  | `sweep_04` | 17.3 M | 1.29 M | 186 | 24 |
  | `sweep_11` | 7.48 M | 2.02 M | 139 | 37 |
  | `sweep_12` | 14.1 M | 1.69 M | 121 | 49 |
  | `sweep_07` | 9.88 M | 0.51 M | 119 | 20 |
  | `sweep_08` | 6.25 M | 2.22 M | 105 | 45 |
  | `sweep_10` | 2.93 M | 0.71 M | 43 | 24 |
  | `sweep_09` | 2.40 M | 0.43 M | 35 | 11 |
  | `sweep_03` | 1.99 M | 0.10 M | 33 | 2.0 |
  | `confirm_02` | 1.44 M | 0.03 M | 30 | 0.6 |
  | `confirm_03` | 1.63 M | 0.43 M | 17 | 12 |
  | `sweep_01` | 0.22 M | 0.02 M | 4.6 | 0.35 |
  | `sweep_05` | 0.11 M | 0.02 M | 2.4 | 0.42 |

  3–75 times fewer nodes. Without `confirm_01`, the 14 other inputs went from 171 M nodes and 1768 s in all to
  14.9 M and 361 s: 11.5 times fewer nodes, 4.9 times faster. The "before" times come from the tuning rounds, also
  run several at a time; `confirm_01`'s is the uncapped command-line run of 2026-11-14 (it timed out at 30 minutes
  in the round), and its schedule now is the same, file for file. Day 2, where it has a schedule, takes 1.1–8 times
  fewer nodes.

* **Each node costs more:** about $n_\text{workers} \times 64 \times 2$ terms per value of $\mu$, a few values per
  node. The default power, 2, is written out instead of calling `integer_power`, which took about 40% of the time.
* **Still open** ([Future work](../explanation/future-work.md#search-performance)):
  * sets per worker that count only the slots in their own domains, which would be tighter but must be kept up to
    date as domains narrow;
  * a rest look-ahead;
  * symmetry between identical workers.
