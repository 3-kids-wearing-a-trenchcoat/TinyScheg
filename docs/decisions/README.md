# Architecture Decision Records

This folder records TinyScheg's significant design decisions as
[Architecture Decision Records](https://adr.github.io/) (ADRs), in the format proposed by
[Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

An ADR records a decision and the reasoning behind it, not whether it's implemented — implementation status is
tracked in the rest of the docs.

## Statuses

* **Proposed** — under consideration, not yet settled.
* **Accepted** — decided.
* **Superseded** — replaced by a later ADR, which is linked. Superseded ADRs are kept, not deleted, so the reasoning
  behind past decisions isn't lost.

ADRs aren't edited after they're accepted, other than to change their status. To change a decision, write a new
ADR that supersedes the old one.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-model-scheduling-as-csp.md) | Model scheduling as a constraint satisfaction problem | Accepted |
| [0002](0002-backtracking-with-forward-checking.md) | Backtracking search with forward checking | Accepted |
| [0003](0003-variable-ordering-mrv-degree.md) | Order variables by MRV and the degree heuristic; no value ordering | Accepted |
| [0004](0004-branch-and-bound-with-monotone-penalty.md) | Find the best schedule with branch and bound over a monotone penalty | Accepted |
| [0005](0005-weighted-sum-of-normalized-penalties.md) | Score as a weighted sum of normalized per-worker penalties | Accepted |
| [0006](0006-convex-function-for-workload-fairness.md) | Use a convex function for workload fairness | Accepted |
| [0007](0007-greedy-bound-for-worst-rest-deficit.md) | Bound the worst rest deficit greedily | Accepted |
| [0008](0008-undo-through-trail.md) | Undo assignments through a trail | Accepted |
| [0009](0009-yaml-input-with-time-based-variations.md) | YAML input with time-based post variations | Accepted |
| [0010](0010-python-rewrite.md) | Rewrite in Python | Accepted |
| [0011](0011-no-output-for-infeasible-inputs.md) | No output for infeasible inputs | Accepted |
| [0012](0012-deterministic-path-independent-scoring.md) | Deterministic, path-independent scoring and output | Accepted |

## Template

```markdown
# NNNN. Title

**Status:** Proposed | Accepted | Superseded by [NNNN](NNNN-....md)

## Context

What is the issue that motivates this decision?

## Decision

What is the change being made?

## Consequences

What becomes easier or harder because of this decision?
```
