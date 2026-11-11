# `output` package: `grid` and `csv_writer`

Sources: [`src/tinyscheg/output/grid.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/output/grid.py) and
[`src/tinyscheg/output/csv_writer.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/output/csv_writer.py)

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
  cell, or `None` if the post isn't active then. A shift covering several rows has its index in each of them; this is
  what spreadsheet formats merge, and it tells consecutive shifts apart even when the same workers fill both.
* `shift_names` — `tuple[str, ...]`: for each shift, its workers' names in stable slot order, joined with `" & "`.

#### `text(row, column) -> str`

The cell as shown: the covering shift's names, or `""` if the post isn't active then.

### `build_grid(posts, shifts, workers, assignment) -> Grid`

Lays a schedule out as a grid.

* `posts` — all posts, in input order. Each gets a column, even one with no shifts in the period.
* `shifts` — the schedule's shifts, in stable order.
* `workers` — all workers, in input order.
* `assignment` — a worker index per slot, in stable slot order, as found by the
  [search](search.md#find_first_scheduleproblem-searchresult).

Every shift's start and end is a row boundary, so each shift covers whole, consecutive rows.

## `csv_writer` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_csv_writer.py`).

### `write_csv(grid, path) -> None`

Writes a grid as CSV, with the standard library's `csv` module, replacing the file if it exists:

* UTF-8 with a byte order mark (`CSV_ENCODING = "utf-8-sig"`), so Excel shows names in any script correctly;
* a header row of `start`, `end`, then the post names;
* times as ISO 8601 (`2025-01-01T06:00:00`);
* each cell's `text`, so a shift covering several rows has its names repeated in each.
