# 0012. Deterministic, path-independent scoring and output

**Status:** Accepted, amended by [0027](0027-incremental-scoring-for-steering.md) (path independence is required of
what decides the result, not of what only steers the search)

## Context

The search compares the penalties of partial and complete schedules against the pocket (see
[0004](0004-branch-and-bound-with-monotone-penalty.md)). These comparisons are only meaningful if a schedule's
penalty is well defined. Two things can undermine that:

* **Path dependence.** If penalties are updated incrementally as slots are assigned and unassigned, the same state
  can end up with slightly different penalties depending on the order of the operations that led to it. Floating-point
  arithmetic in particular isn't exactly reversible: $(x + a) - a$ isn't always exactly $x$, and the order of
  additions affects the result.
* **Nondeterministic iteration.** Python's iteration order over sets of objects depends on memory addresses, which
  differ between runs. If such orders influence the search, the same input can produce different schedules on
  different runs.

## Decision

Determinism is a requirement **on par with monotonicity**:

1. **Path independence:** for a given configuration of weights and parameters, every schedule state, partial or
   complete, maps to exactly **one** penalty, regardless of how the search reached it.
2. **Reproducibility:** the same input and configuration always produce the same output.

To achieve this:

* Penalties are computed from scratch from the current assignment until incremental scoring is introduced. When it
  is, it must be exactly reversible (e.g. exact arithmetic), and the from-scratch computation serves as a test oracle
  for it.
* Nothing the search does may depend on the iteration order of sets or other unordered collections. Slots and
  workers are ordered by stable keys (e.g. slots by time, then post, then index; workers by input order).
* Ties have a fixed rule: when a new complete schedule's penalty equals the pocket's, the pocket keeps the schedule
  that was found first.

## Consequences

* Results can be reproduced, tested and compared across runs.
* Incremental scoring with floating-point arithmetic is ruled out unless it is shown to be exactly path-independent.
  This favours exact arithmetic (e.g. `fractions.Fraction`, or integers such as minutes with scaled weights), which
  in turn favours $\varphi(x) = x^p$ with an integer $p$ over $\varphi(x) = e^{ax} - 1$, since the exponential can't
  be computed exactly.
* Using sets for membership checks remains fine; only *iterating* over them in a way that affects the search is
  ruled out.
