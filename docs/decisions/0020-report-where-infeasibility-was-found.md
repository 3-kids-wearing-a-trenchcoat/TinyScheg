# 0020. Report where infeasibility was found

**Status:** Accepted.

## Context

[ADR 0011](0011-no-output-for-infeasible-inputs.md) decided that when no legal schedule exists, TinyScheg reports
that and produces no output, and left explaining *why* to [future work](../explanation/future-work.md#explaining-infeasibility).
A full explanation (every cause, or a minimal set of conflicting requirements) is hard to compute. But some
information about what went wrong is available for free, at the point where TinyScheg finds out, and is enough to
point whoever is responsible for the schedule in the right direction.

## Decision

When the input has no solution, TinyScheg writes no output file and announces on the command line that no schedule
could be made, describing the point at which it found that out. The description covers whatever was encountered, not
an exhaustive list of problems:

* **Before the search:** every slot that no worker can fill (no available worker has its role), e.g.
  `no worker can fill desk, 2025-01-02 08:00–12:00 (role "supervisor")`. These are found by checking every slot's
  initial domain, so all of them are listed.
* **During the search:** if the search runs out of options, the deepest point it reached (how many slots it managed
  to fill) and the slot it couldn't fill there. This is a hint about where the problem is, not a proof of its cause.

The message is printed to standard error, TinyScheg exits with a non-zero status, and no file is written to the
output path.

## Consequences

* An unsolvable input is never silent, and the cheap cases (e.g. a role nobody available has) are named exactly.
* The search keeps track of the deepest point it reached, which costs next to nothing.
* Explaining infeasibility fully remains [future work](../explanation/future-work.md#explaining-infeasibility).
