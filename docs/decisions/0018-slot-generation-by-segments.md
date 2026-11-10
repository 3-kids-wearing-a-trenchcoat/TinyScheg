# 0018. Generate shifts per segment

**Status:** Accepted.

## Context

Posts are templates for shifts: they have a shift length, role requirements, an optional daily activity window, and
optional variations that change the requirements during recurring daily windows. Turning a post into concrete
shifts over the schedule period requires deciding how shifts line up with these windows.

The first Python implementation generated one continuous sequence of shifts per post, starting at the schedule's
start, with each shift's requirements chosen by the variation in effect at its start time. Shifts could then run
across a variation's boundary under the wrong requirements: with 3-hour shifts and a 19:00–07:00 night variation, the
18:00–21:00 shift would be staffed by day rules, leaving 19:00–21:00 under-staffed.

The earlier Java implementation handled daily activity windows by starting each day's shifts at the window's opening
and cutting the last one off at its close (and at the schedule's end). The original design idea was also a
"factory" per variation, each generating shifts within its own window.

## Decision

For each post, the schedule period is split into **segments** at every boundary where the rules change: the
schedule's start and end, the openings and closings of the post's daily activity window, and the starts and ends of
its variations. Windows that cross midnight are included from the day they open, so a window that opened the day
before the schedule starts still applies.

* A post without a `time` window is active throughout the schedule period. A variation only applies **where its
  post is active**.
* Within a segment the rules are constant: those of the variation in effect, otherwise the post's general case.
* In each segment, shifts are laid back to back from the segment's start. If the segment's length isn't a multiple
  of the shift length, the last shift is cut off at the segment's end (a shorter, "dangling" shift).
* Each shift gets one slot per required worker of each role. A variation requiring no workers produces shifts with
  no slots, closing the post during its window.
* Two variations of the same post that overlap in time are a **validation error**.
* A time window whose start equals its end (e.g. `"00:00-00:00"`) covers the full 24 hours.
* Slots are ordered by start, end, the post's position in the input, the role's position in the post's role list,
  and index, and receive their stable IDs in that order.

## Consequences

* Staffing always matches the requirements in effect: no shift crosses a boundary where the rules change.
* Dangling shifts appear wherever a window isn't a multiple of the shift length. These are allowed rather than
  rejected: they're usually, but not always, an input mistake. Whether to handle them differently is left for later
  (see [Future work](../explanation/future-work.md#dangling-shifts)).
* If this scheme doesn't work well in practice, it will be revisited.
