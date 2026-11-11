# Output format

> [!IMPORTANT]
> **Partially implemented.** The grid and CSV are implemented ([`output`](api/output.md)); XLSX and ODS, and
> choosing the format by extension (in the command-line interface), aren't.

TinyScheg writes the finished schedule as a grid of time against post
([ADR 0019](../decisions/0019-output-as-a-time-by-post-grid.md)), in one of three formats chosen by the output file's
extension:

| Extension | Format | Notes |
|-----------|--------|-------|
| `.csv`    | CSV    | Unicode (UTF-8 with a byte order mark, so Excel recognizes the encoding and shows names in any script, e.g. Hebrew, correctly); times as ISO 8601 text (`YYYY-MM-DDTHH:MM:SS`). |
| `.xlsx`   | Microsoft Excel | Times as date-time cells; multi-row shifts as merged cells. |
| `.ods`    | OpenDocument spreadsheet | Times as date-time cells; multi-row shifts as merged cells. |

> [!NOTE]
> The first working version writes CSV only. XLSX and ODS are planned to follow.

## Layout

* **Columns:** `start`, `end`, then one column per post, in the order the posts appear in the input, headed by the
  post's name.
* **Rows:** one per interval between consecutive shift boundaries, taken over all posts together, in time order.
  Intervals during which no post is active are left out.
* **Cells:** the names of the workers assigned to the post during that interval, in stable slot order, joined with
  `" & "`. An empty cell means the post isn't active then.
* **Shifts covering several rows** are merged cells in XLSX and ODS. In CSV, the names are repeated in every row the
  shift covers.

For example, with a "front gate" post of 3-hour shifts that needs two workers from 19:00 to 07:00, and a "desk" post
of 4-hour shifts open from 08:00 to 20:00, a schedule starting at 06:00 begins:

| start               | end                 | front gate    | desk |
|---------------------|---------------------|---------------|------|
| 2025-01-01T06:00:00 | 2025-01-01T07:00:00 | Enkidu & Anne |      |
| 2025-01-01T07:00:00 | 2025-01-01T08:00:00 | Jack          |      |
| 2025-01-01T08:00:00 | 2025-01-01T10:00:00 | Jack          | Jill |
| 2025-01-01T10:00:00 | 2025-01-01T12:00:00 | Anne          | Jill |
| 2025-01-01T12:00:00 | 2025-01-01T13:00:00 | Anne          | Bob  |

Here the front gate's 06:00–07:00 shift is cut short at the end of the night variation (Enkidu fills its
`security` slot, which comes first in the night variation's roles, and Anne its `any` slot), its 07:00–10:00 shift covers
two rows, and so do the desk's 08:00–12:00 and the front gate's 10:00–13:00 shifts.

## Reading the output back

The output is meant to be read back in as input by the planned
[schedule history](../explanation/future-work.md#schedule-history) feature, so post and worker names match the input
exactly and times are absolute. This is also why worker names must not contain `" & "`.

In CSV, consecutive rows with identical contents in a post's column are read as a single shift. This is exact as long
as `min_rest` is positive; with `min_rest: 0`, two consecutive shifts staffed by the same workers would be read back
as one.

Which worker fills which role isn't part of the output.
