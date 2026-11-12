# Architecture Decision Records

This folder records TinyScheg's significant design decisions as
[Architecture Decision Records](https://adr.github.io/) (ADRs), in the format proposed by
[Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

An ADR records a decision and the reasoning behind it, not whether it's implemented — implementation status is
tracked in the rest of the docs.

## Statuses

* **Proposed** — under consideration, not yet settled.
* **Accepted** — decided.
* **Amended** — still accepted, but part of it (named in its status) is changed by a later ADR, which is linked.
* **Superseded** — replaced by a later ADR, which is linked. Superseded ADRs are kept, not deleted, so the reasoning
  behind past decisions isn't lost.

ADRs aren't edited after they're accepted, other than to change their status. To change a decision, write a new
ADR that supersedes the old one.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-model-scheduling-as-csp.md) | Model scheduling as a constraint satisfaction problem | Accepted |
| [0002](0002-backtracking-with-forward-checking.md) | Backtracking search with forward checking | Accepted, amended by [0017](0017-plain-forward-checking-and-pruning-on-ties.md) and [0024](0024-cheapest-first-value-order-and-workload-bound.md) |
| [0003](0003-variable-ordering-mrv-degree.md) | Order variables by MRV and the degree heuristic; no value ordering | Accepted, amended by [0024](0024-cheapest-first-value-order-and-workload-bound.md) |
| [0004](0004-branch-and-bound-with-monotone-penalty.md) | Find the best schedule with branch and bound over a monotone penalty | Accepted, amended by [0017](0017-plain-forward-checking-and-pruning-on-ties.md) |
| [0005](0005-weighted-sum-of-normalized-penalties.md) | Score as a weighted sum of normalized per-worker penalties | Accepted |
| [0006](0006-convex-function-for-workload-fairness.md) | Use a convex function for workload fairness | Accepted, amended by [0013](0013-availability-weighted-workload.md) and [0021](0021-power-function-for-workload-fairness.md) |
| [0007](0007-greedy-bound-for-worst-rest-deficit.md) | Bound the worst rest deficit greedily | Superseded by [0014](0014-exact-worst-rest-deficit.md) |
| [0008](0008-undo-through-trail.md) | Undo assignments through a trail | Superseded by [0016](0016-undo-through-change-records-on-the-call-stack.md) |
| [0009](0009-yaml-input-with-time-based-variations.md) | YAML input with time-based post variations | Accepted |
| [0010](0010-python-rewrite.md) | Rewrite in Python | Accepted |
| [0011](0011-no-output-for-infeasible-inputs.md) | No output for infeasible inputs | Accepted |
| [0012](0012-deterministic-path-independent-scoring.md) | Deterministic, path-independent scoring and output | Accepted, amended by [0027](0027-incremental-scoring-for-steering.md) |
| [0013](0013-availability-weighted-workload.md) | Weight the workload penalty by availability | Accepted, amended by [0015](0015-normalize-workload-by-packable-maximum.md) |
| [0014](0014-exact-worst-rest-deficit.md) | Calculate the worst rest deficit exactly | Accepted |
| [0015](0015-normalize-workload-by-packable-maximum.md) | Normalize workload by each worker's packable maximum | Accepted |
| [0016](0016-undo-through-change-records-on-the-call-stack.md) | Undo through change records on the call stack | Accepted |
| [0017](0017-plain-forward-checking-and-pruning-on-ties.md) | Plain forward checking, and pruning on ties | Accepted |
| [0018](0018-slot-generation-by-segments.md) | Generate shifts per segment | Accepted |
| [0019](0019-output-as-a-time-by-post-grid.md) | Output the schedule as a time-by-post grid | Accepted |
| [0020](0020-report-where-infeasibility-was-found.md) | Report where infeasibility was found | Accepted |
| [0021](0021-power-function-for-workload-fairness.md) | Use a whole-number power for workload fairness | Accepted |
| [0022](0022-scoring-parameters-with-defaults-and-input-overrides.md) | Scoring parameters: named defaults, optionally set in the input | Accepted, amended by [0023](0023-dislikes-outweigh-likes.md) and [0028](0028-rest-factor-default-2-5.md) |
| [0023](0023-dislikes-outweigh-likes.md) | A dislike outweighs a like: the neutral partner value stays below 1/2 | Accepted |
| [0024](0024-cheapest-first-value-order-and-workload-bound.md) | Speed up branch and bound: cheapest-first value order and a lower bound on workload | Accepted |
| [0025](0025-order-interchangeable-slots.md) | Fill a shift's interchangeable slots in ascending worker order | Accepted |
| [0026](0026-workload-counts-shifts-and-hours.md) | Workload counts shifts as well as hours | Accepted |
| [0027](0027-incremental-scoring-for-steering.md) | Incremental scoring to steer the search, exact scoring to decide it | Accepted |
| [0028](0028-rest-factor-default-2-5.md) | Default rest factor 2.5 | Accepted |
| [0029](0029-schedule-history-input.md) | Schedule history: previous inputs and their schedules, read back as fixed history | Accepted, amended by [0031](0031-history-as-the-filled-part-of-one-schedule.md) |
| [0030](0030-history-in-scoring.md) | History in scoring: the history and the new schedule scored as one | Accepted, amended by [0031](0031-history-as-the-filled-part-of-one-schedule.md) |
| [0031](0031-history-as-the-filled-part-of-one-schedule.md) | History as the already-filled part of one schedule | Accepted |

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
