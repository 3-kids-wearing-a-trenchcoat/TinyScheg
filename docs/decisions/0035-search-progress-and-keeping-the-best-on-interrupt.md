# 0035. The search shows its progress, and Ctrl+C keeps the best schedule found so far

**Status:** Accepted.

## Context

Branch and bound runs to the end, however long that takes: a time or node limit was decided against (2026-11-11,
confirmed 2026-11-12, see [Future work](../explanation/future-work.md#search-performance)), since long runs for a
single schedule aren't to be forbidden in real use. But while it runs, the command line only reports each better
schedule as it's found (`found penalty 8.38 after 12 s`, one line each), which says nothing about how far along the
search is or how much longer it will take; and Ctrl+C stops it without writing anything, so a long run stopped by
hand is lost.

The user (2026-11-14): a schedule should be able to run "as long as it needs" (a particularly long schedule, say),
but the user, and Claude during development, should have some way of knowing how far along the search is and how
much longer it's going to take, in a line that updates in place. The information shown today should stay, updated
in place along with the progress, not printed as new lines that push the progress line back. Time caps used during
development (10 or 30 minutes) are arbitrary, there to keep the work manageable, not requirements.

## Decision

1. **Progress is the share of the search space finished.** The root counts as 1. A node's weight is split equally
   among its children, the values left to try for the slot it fills, and when a branch is finished (searched to
   the end, pruned, or a dead end), its weight is added to a running total. The total only ever rises and reaches 1
   when the search ends. The time left is estimated as the time elapsed times the share left over the share
   finished. That estimate is rough, and labelled so: the most promising values are tried first, so early branches
   take longest and later ones are pruned fast, and the estimate starts high. It's only shown once a minimum share
   is finished.
2. **On a terminal, a block of two lines redrawn in place:** the best schedule so far (its penalty and parts, and
   when it was found), and the progress (share finished, nodes, time elapsed, rough time left). It's redrawn at most
   a few times a second, and the search looks at the clock only every few thousand nodes, so it doesn't slow the
   search noticeably. Lines are cut to the terminal's width, since wrapped lines would break the redrawing. It uses
   the standard library and two standard terminal codes (cursor up, clear line), enabled on Windows consoles that
   need it; where they can't be used, one line redrawn with a carriage return. When the search ends, the block
   stays as last drawn, and the usual summary follows.
3. **Not on a terminal** (output to a file or a pipe): each better schedule on its own line, as before, and a plain
   progress line at a longer interval, so logs stay readable.
4. **Ctrl+C writes the best schedule found so far,** saying that it's the best found, not proven the best, and how
   much of the search was finished. The program still exits with the interrupted code (130), so a script can tell
   the run didn't finish. If no schedule has been found yet, nothing is written, as before.
5. **The progress only observes the search:** which branches are searched, the schedule found and the node counts
   are exactly the same with or without it.

Every interval and threshold is a named constant.

Rejected:

* **A library for the display** (`tqdm`, `rich`). The progress measure has to come from the search either way; the
  display left is a few dozen lines. `tqdm` draws one bar per line, so a two-line block means a text-only bar
  stacked on another, and its stacked bars can break when anything else writes to the terminal; its time estimate
  is the same calculation. `rich` does multi-line live displays well, but brings several libraries of its own. A
  new dependency also goes into the environment, the PyPy setup and the future distribution.
* **The gap to the best possible schedule** as the progress measure. It would say how much better a schedule could
  still be, but keeping it current means bounding every branch not yet searched, at a real cost per node, and with
  bounds as weak as ours near the root it would stay wide for most of a run.
* **A time or node limit,** again: stopping is left to the user, who can now see the progress before deciding.

## Consequences

* A long run can be followed, and stopped by hand without losing what it found. A schedule written after Ctrl+C
  may not be the best one; the message and the exit code say so.
* The development tools can log the same progress, so how long a run has left is read from the run rather than
  guessed from earlier ones.
* The share finished advances unevenly (pruning a large branch makes it jump), and the time left is only a rough
  guide, best late in the run.
