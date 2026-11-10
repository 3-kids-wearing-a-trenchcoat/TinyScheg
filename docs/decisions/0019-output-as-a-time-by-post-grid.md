# 0019. Output the schedule as a time-by-post grid

**Status:** Accepted.

## Context

The schedule has to be readable by the people working it, and it has to be readable back in by TinyScheg: the
planned [schedule history](../explanation/future-work.md#schedule-history) feature takes a previously generated
schedule as input. CSV was originally chosen because it's universally supported and simple to work with, but
spreadsheets are what people usually open and share schedules in, so the output should be available as
spreadsheets too, in both an open format and Microsoft Excel's.

People read a roster as a grid of time against post. Posts don't share shift boundaries, though: each post has its
own shift length, activity window and variations ([ADR 0018](0018-slot-generation-by-segments.md)), so a grid
needs a rule for what a row is, and a shift may cover several rows.

## Decision

The output is a single **grid**:

* The columns are `start`, `end`, then one column per post, in input order, headed by the post's name.
* The rows are the intervals between consecutive shift boundaries, taken over **all** posts together, in time order.
  Intervals during which no post is active are left out.
* A cell holds the names of the workers assigned to that post during the row's interval, in stable slot order,
  joined with `" & "` (e.g. `Alice & Bob`). Roles aren't shown.
* An empty cell means the post isn't active (or is closed by a variation) during that interval. Since infeasible
  inputs produce no output ([ADR 0011](0011-no-output-for-infeasible-inputs.md)), there are never unassigned slots.
* A shift covering several rows is shown as **vertically merged cells** in spreadsheet formats. In CSV, which can't
  merge cells, its names are repeated in every row it covers.

The grid is written in three formats, chosen by the output file's extension:

* **CSV** (`.csv`) — UTF-8 with a byte order mark, so that Excel displays non-Latin names correctly; times as
  ISO 8601 text. Written with the standard library's `csv` module.
* **XLSX** (`.xlsx`, Microsoft Excel) — written and read with `openpyxl`.
* **ODS** (`.ods`, OpenDocument) — written and read with `odfpy`.

In spreadsheet formats, `start` and `end` are stored as real date-time cells, so they sort and filter correctly.
Worker names must not contain `" & "`; such a name is an input error.

The walking skeleton writes CSV only; XLSX and ODS follow once it works end to end.

## Consequences

* The output reads like a hand-made roster, while still being re-readable: post and worker names match the input
  exactly, and times are absolute.
* Reading it back, merged cells in XLSX/ODS give each shift's exact boundaries. In CSV, consecutive rows with the
  same cell contents are merged back into one shift. This is exact as long as the minimum rest period is positive,
  since no worker can then work two back-to-back shifts at the same post. With a minimum rest of 0, two consecutive
  shifts staffed by the same workers would be read back as one longer shift, slightly changing the rest score. This
  is a known limitation.
* Which worker fills which role isn't recorded. Scoring doesn't need it (workload, rest and likes depend only on who
  works where and when), but it's lost for anyone reading the schedule.
* Two new dependencies, `openpyxl` and `odfpy`, both pure Python. The standard library can't read or write either
  format; writing them by hand (both are zipped XML) would be brittle, and reading them back harder still.
* Rows can be uneven in length, and a schedule with many posts on unaligned shift lengths gets many short rows.
