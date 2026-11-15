# `output` package: `grid`, `writers` and the format writers

Sources: [`src/tinyscheg/output/grid.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/output/grid.py),
[`src/tinyscheg/output/writers.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/output/writers.py) and
[`src/tinyscheg/output/csv_writer.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/output/csv_writer.py),
[`src/tinyscheg/output/xlsx_writer.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/output/xlsx_writer.py) and
[`src/tinyscheg/output/ods_writer.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/output/ods_writer.py)

See [Output format](../output-format.md) for the layout and formats, and
[ADR 0019](../../decisions/0019-output-as-a-time-by-post-grid.md) for why. The grid is the internal table every format
is written from; each format has a writer that translates it.

## `grid` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_grid.py`).

### `class Grid(columns, rows, cells, shift_names)`

A schedule as a table. Immutable.

* `columns` — `tuple[str, ...]`, the post names, in input order.
* `rows` — `tuple[DateTimeRange, ...]`, the intervals between consecutive shift boundaries over all posts, in time
  order. Intervals during which no post is active are left out.
* `cells` — `tuple[tuple[int | None, ...], ...]`: for each row and column, the index of the shift covering that
  cell (its position in the shifts the grid was built from), or `None` if the post isn't active then. A shift covering several rows has its index in each of them; this is
  what spreadsheet formats merge, and it tells consecutive shifts apart even when the same workers fill both.
* `shift_names` — `tuple[str, ...]`: for each shift, its workers' names in stable slot order, joined with `" & "`.

#### `text(row, column) -> str`

The cell as shown: the covering shift's names, or `""` if the post isn't active then.

#### `spans() -> tuple[Span, ...]`

Each shift's block of cells, which spreadsheet formats show as one merged cell: a `Span(column, first_row, last_row,
shift_index)` (rows inclusive, all indexes 0-based) per shift in the grid, by column, then by first row. Consecutive
shifts filled by the same workers are separate spans, since their cells hold different shift indexes.

### `build_grid(posts, shifts, workers, assignment) -> Grid`

Lays a schedule out as a grid.

* `posts` — all posts, in input order. Each gets a column, even one with no shifts in the period.
* `shifts` — the shifts to show, in stable order: the schedule's, or with a history, the new period's
  (`Problem.new_shifts`).
* `workers` — all workers, in input order.
* `assignment` — a worker index per slot (by `slot.index`), in stable slot order, as found by the
  [search](search.md#search-module).

Every shift's start and end is a row boundary, so each shift covers whole, consecutive rows.

## `writers` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_cli.py`).

Chooses the output format by file extension. Kept out of the command-line code so that any front end can use it.

* `WRITERS` — `dict[str, Writer]`, the writer for each supported extension (lower case). `".csv"`, `".xlsx"` and
  `".ods"`.
* `DEFAULT_EXTENSION` — `".csv"`, used when no output path is given.

### `writer_for(path) -> Writer`

The writer for `path`'s extension, in any case. **Raises** `UnsupportedFormatError` (a `ValueError`) naming the
supported extensions if there's none, including for a path with no extension.

### `write_schedule(grid, path) -> None`

Writes `grid` to `path` in the format its extension names, replacing the file if it exists.

## `csv_writer` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_csv_writer.py`).

### `write_csv(grid, path) -> None`

Writes a grid as CSV, with the standard library's `csv` module, replacing the file if it exists:

* UTF-8 with a byte order mark (`CSV_ENCODING = "utf-8-sig"`), so Excel shows names in any script correctly;
* a header row of `start`, `end`, then the post names;
* times as ISO 8601 (`2025-01-01T06:00:00`);
* each cell's `text`, so a shift covering several rows has its names repeated in each.

## `xlsx_writer` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_xlsx_writer.py`, reading the workbook back with openpyxl).

### `write_xlsx(grid, path) -> None`

Writes a grid as an Excel workbook with openpyxl, replacing the file if it exists. One sheet, `SHEET_TITLE`
(`"schedule"`):

* a header row of `start`, `end`, then the post names, in bold;
* times as date-time cells, shown as `DATETIME_FORMAT` (`yyyy-mm-dd hh:mm`);
* each shift's names once, in the first cell of its [span](#spans-tuplespan), merged over the rows it covers and
  centred vertically; cells where the post isn't active are left empty;
* the header row and the time columns frozen;
* the time columns `TIME_COLUMN_WIDTH` (17) characters wide, and each post's column as wide as its longest text plus
  `COLUMN_PADDING` (2), at least `MIN_POST_COLUMN_WIDTH` (10).

## `ods_writer` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_ods_writer.py`, reading the spreadsheet back with odfpy).

### `write_ods(grid, path) -> None`

Writes a grid as an OpenDocument spreadsheet with odfpy, replacing the file if it exists, laid out as
[`write_xlsx`](#write_xlsxgrid-path-none) lays out a workbook, and with the same named constants for the sheet title,
time headers and column widths:

* times as date cells (`office:date-value`), with a date style showing `yyyy-mm-dd hh:mm` and that text in the cell;
* a span's first cell holding its names, with `table:number-rows-spanned` if it covers several rows, and covered
  cells (`table:covered-table-cell`) below it;
* the header row and time columns frozen through the document's view settings;
* column widths in characters converted at `CHARACTER_WIDTH_CM` (0.23 cm) per character.
