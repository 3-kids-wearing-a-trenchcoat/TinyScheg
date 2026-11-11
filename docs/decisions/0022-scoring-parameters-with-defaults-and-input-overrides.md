# 0022. Scoring parameters: named defaults, optionally set in the input

**Status:** Accepted. Amended by [0023](0023-dislikes-outweigh-likes.md) (`neutral_partner` must be less than 1/2).

## Context

The [scoring](../explanation/scoring.md) design has parameters whose values were open: the weights $a$, $b$, $c$ of
the likes, workload and rest penalties, the power $p$ of the workload curve
([ADR 0021](0021-power-function-for-workload-fairness.md)), the rest factor $\gamma$, and the like values $\alpha$
and $\beta$. Their best values aren't known yet, and the mathematics itself may change, so they should be easy to
tune; and TinyScheg is meant for any scheduling situation, whose users may weigh things differently.

Two properties of the formulas shape the parameters:

* The likes penalty is divided by $\beta$ to normalize it, so only the ratio $\alpha / \beta$ matters.
* The rest penalty is zero after a shift $s$ unless $\gamma \cdot |s|$ exceeds the minimum rest period: with 6 hours'
  minimum rest and 3-hour shifts, any $\gamma \leq 2$ disables it.

## Decision

Every scoring parameter has a default, defined **once, as a named constant** in the code, and can be overridden in
an optional `scoring` section of the input's `settings` (see [Input format](../reference/input-format.md#scoring)):

| Parameter | Input field | Default | Allowed values |
|-----------|-------------|---------|----------------|
| Weights $a$, $b$, $c$ | `weights: {likes, workload, rest}` | 0.25, 0.5, 0.25 | at least 0, not all 0 |
| Workload power $p$ | `workload_power` | 2 | a whole number, at least 2 |
| Rest factor $\gamma$ | `rest_factor` | 3 | at least 1 |
| Neutral partner $\alpha / \beta$ | `neutral_partner` | 1/3 | more than 0, less than 1 |

* **Weights are relative**: they're divided by their sum, so $a + b + c = 1$ as in
  [ADR 0005](0005-weighted-sum-of-normalized-penalties.md) without the input having to add up exactly (0.33, 0.33,
  0.34 or 1, 2, 1 both work).
* **Workload gets the largest weight.** It's the fairness criterion, and its normalized value swings least between
  a fair and an unfair schedule (a perfectly fair schedule already scores about 4.1 of 9 on the example), so an equal
  weight would underweight it.
* With these defaults, on the example input, moving one 3-hour shift of imbalance outweighs one disliked pairing
  about 2:1, and an hour of rest below target costs about a fifth of a disliked pairing.
* **Dislikes stay soft**: they're discouraged by the penalty, never forbidden. A hard rule could make inputs
  unsolvable over a preference.

## Consequences

* Tuning needs no code change, and changing a default is a one-line change.
* The input gains an optional section, which needs parsing and validation like the rest.
* Scores are only comparable between runs with the same parameters.
