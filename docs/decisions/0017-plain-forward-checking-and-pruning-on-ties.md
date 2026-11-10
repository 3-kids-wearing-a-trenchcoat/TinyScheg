# 0017. Plain forward checking, and pruning on ties

**Status:** Accepted. Amends [0002](0002-backtracking-with-forward-checking.md) and
[0004](0004-branch-and-bound-with-monotone-penalty.md).

## Context

[ADR 0002](0002-backtracking-with-forward-checking.md) included assigning a slot immediately when propagation
reduces its domain to a single worker. But a domain of size 1 is the smallest possible, so MRV variable ordering
picks that slot next anyway. Assigning it during propagation adds cascading recursion and assignments outside the
normal order without saving any work.

[ADR 0004](0004-branch-and-bound-with-monotone-penalty.md) prunes partial schedules whose penalty is higher than the
pocket's. With the fixed tie rule of [ADR 0012](0012-deterministic-path-independent-scoring.md) — on equal penalties,
the schedule found first stays in the pocket — a schedule with an *equal* penalty can never replace the pocket
either.

## Decision

* Propagation is **plain forward checking**, in a single pass: after assigning a worker to a slot, remove that
  worker from the domain of every unassigned slot constrained with it. If any domain becomes empty, the branch fails.
  Slots left with a single worker are **not** assigned automatically.
* A partial schedule is pruned when its penalty is **greater than or equal to** the pocket's.
* The penalty is evaluated on entering each search step, after the previous step's propagation, so the pruning check
  always sees the full current state.
* Variable ordering ends with a final tie-break on the slot's stable position, so the choice is always deterministic:
  smallest domain (MRV), then most unassigned constrained slots (degree), then stable slot order.

## Consequences

* Propagation is simpler and needs no iteration counter.
* Single-worker slots are still assigned next, through MRV.
* Pruning on ties skips branches that could never change the result.
