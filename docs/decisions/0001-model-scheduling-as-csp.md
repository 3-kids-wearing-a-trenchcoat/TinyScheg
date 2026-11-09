# 0001. Model scheduling as a constraint satisfaction problem

**Status:** Accepted

## Context

A shift schedule has to satisfy hard rules: a worker can only work when available, some positions require specific
roles, and a worker can't take a shift during, immediately before or immediately after a shift they're already
assigned to. Among the schedules that satisfy these rules, some are better than others in terms of fairness and
personal preferences.

## Decision

Model scheduling as a constraint satisfaction problem (CSP):

* the **variables** are **slots**: one per worker needed, per shift, per post;
* the **values** are **workers**, and each slot's domain is the set of workers who can fill it;
* the **constraints** are the hard rules: availability and role as unary constraints, and difference constraints
  between slots that overlap or are closer than the minimum rest period.

Fairness and preferences are *not* modelled as CSP constraints. They're handled by a separate penalty score
(see [0005](0005-weighted-sum-of-normalized-penalties.md)).

## Consequences

* Well-known CSP techniques apply directly: constraint propagation, and the MRV and degree heuristics.
* Unary constraints can be applied once, when slots are created.
* Because soft constraints live outside the CSP, finding *a* solution isn't enough; the search must compare
  solutions (see [0004](0004-branch-and-bound-with-monotone-penalty.md)).
