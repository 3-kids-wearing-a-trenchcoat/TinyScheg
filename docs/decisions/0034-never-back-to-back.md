# 0034. A worker is never assigned back-to-back shifts, whatever the minimum rest

**Status:** Accepted.

## Context

Two slots got a difference constraint if they overlapped or were less than the minimum rest (`min_rest`) apart, a
rest of exactly `min_rest` being allowed. So with a `min_rest` of 0, a worker could be given two shifts back to back:
one ending as the other starts.

The user (2026-11-13): the hard constraint on rest is the user's choice of what rest is mandatory, and maximizing
rest beyond it is a soft constraint, the scoring's job. But even with a `min_rest` of 0, no worker may hold
overlapping or adjacent shifts: no shift that starts before or at the moment another of theirs ends, and none that
ends at or after the moment another starts. (The user's original idea was a constraint in shifts, not hours: never the
same shift, the one immediately before or the one immediately after, optionally widened to a radius of two or more
shifts, and from there, maximize rest.)

## Decision

**Two of a worker's shifts must have a rest between them of more than zero and at least `min_rest`.** Back to back
is never allowed; with `min_rest` 0, any gap at all is enough. This applies everywhere the rule is checked: the
problem's difference constraints, the worst possible rest deficit, the independent hard-constraint checker and the
audit's quick legality check.

`min_rest` stays in hours rather than in shifts: with several posts of different shift lengths, "the next shift" is
ambiguous, while a minimum in hours is the same rule for all of them. A radius in shifts could later be a way to enter
it when all shifts have the same length.

## Consequences

* Nothing changes for any `min_rest` above 0 (the default is 6 hours).
* With `min_rest` 0, schedules with back-to-back shifts are no longer legal; some inputs that had a legal schedule may
  not.
