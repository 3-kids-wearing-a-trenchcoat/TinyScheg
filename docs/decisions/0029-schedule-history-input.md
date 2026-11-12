# 0029. Schedule history: previous inputs and their schedules, read back as fixed history

**Status:** Accepted. Amended by [0031](0031-history-as-the-filled-part-of-one-schedule.md) (point 6: history is
assigned time, not unavailability).

## Context

Every run so far creates a schedule from scratch, in which every worker is "fresh". Schedules are usually made for
consecutive periods of 24–48 hours, so two things go wrong at the boundary
([Future work](../explanation/future-work.md#schedule-history)): a worker who took the last shift of one schedule
can get the first shift of the next, breaking the minimum rest; and fairness starts over every period, so small
imbalances accumulate. The output was designed to be read back for this
([ADR 0019](0019-output-as-a-time-by-post-grid.md)).

A schedule file alone says who worked which post when, but not who was away, nor exactly where shifts begin and end
in CSV, which can't merge cells. Between periods, the input itself can change: posts can open, close or change hours
and shift lengths, workers can join or leave.

Decided with the user on 2026-11-12.

## Decision

1. **A previous schedule is a pair: the input it was made for, and its schedule file.** The input gives the period,
   the workers' availability, and the posts, from which the shifts are generated as for any run; the file gives who
   worked each shift. The file is the record of what happened, so a schedule edited by hand after it was written
   (two workers swapping a shift) is read as edited.
2. **Each previous schedule is read with its own input**, which may differ from the current one in anything: posts,
   hours, shift lengths, workers, settings. Workers are matched across inputs **by name**.
3. **The current input lists its history** in an optional top-level `history` section: a list of `input` and
   `schedule` paths, relative to the input file, so that a run is fully described, and can be repeated, from its
   input file alone. A history input's own `history` is ignored: the current input lists everything it counts.
4. **Reading a schedule file** (`parsing/schedule_reader.py`): for each
   shift generated from its input, the names in the cell where it starts, in its post's column. This works the same
   for CSV, XLSX and ODS, and since shift starts come from the input, two consecutive shifts filled by the same
   workers are read correctly even with a minimum rest of 0, which removes the CSV limitation of ADR 0019. Each
   shift's names must be as many as its slots and all workers of that input; anything else is an error naming the
   shift.
5. **What's an error, and what's a warning:**
   * A history period overlapping the current period, or another history period, or ending after the current period
     starts: an input error. History is the past; it's never re-planned.
   * A worker of a history input who isn't in the current input (they've left): a warning; their history is ignored.
   * A worker of the current input who isn't in a history input (they've joined): nothing; they were unavailable
     during that history (ADR 0030).
6. **Minimum rest across the boundary is a hard constraint.** A worker can't be given a shift starting less than the
   current input's `min_rest` after their last history shift ends. In the search, that time is treated as
   unavailability, so the domains already exclude those slots.

How the history affects fairness is [ADR 0030](0030-history-in-scoring.md).

Rejected:

* **The schedule file alone.** Simpler to supply, but it can't tell absence from being given nothing, and CSV shift
  boundaries would have to be guessed from repeated rows.
* **A command-line option** for the history. Quicker for a one-off run, but the run would no longer be described by
  its input file.
* **Following history inputs' own `history` sections.** Convenient for long chains, but how far back fairness reaches
  would then be hidden in other files; listing it in the current input keeps it explicit.

## Consequences

* The reader moves into the package (`parsing/schedule_reader.py`), for all three formats; the development tools
  use it instead of their own CSV-only reader.
* Supplying history means keeping each period's input next to its schedule, which TinyScheg's default output path
  (`<input name>_schedule.<extension>`) already does.
* The schedule file must still match its input: a hand-edited file whose shifts were moved in time, or split, can't
  be read and is reported as an error.
* Which worker filled which role isn't in the file, and isn't needed: history enters only through who worked when.
