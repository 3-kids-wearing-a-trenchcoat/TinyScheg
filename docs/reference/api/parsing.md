# `parsing` package

Sources: [`src/tinyscheg/parsing/input_reader.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/parsing/input_reader.py),
[`src/tinyscheg/parsing/validation.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/parsing/validation.py) and
[`src/tinyscheg/parsing/schedule_reader.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/parsing/schedule_reader.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_input_reader.py`, `tests/test_validation.py`).

Reads the [input file](../input-format.md) into a [`ScheduleInput`](schedule-input.md), in two stages:

1. **Structure:** each entry is checked (required fields, unknown fields, types and values) while it's converted to
   model objects. This includes filling in each variation's unspecified fields from its post.
2. **Validation:** if the structure is valid, the rules that span several entries are checked.

Each stage reports **every** problem it finds at once. The second stage only runs once the first finds none, so
that problems aren't reported twice (e.g. a "like" naming a worker whose own entry was invalid).

## `input_reader` module

### `read_input(path, read_history=True)`

Reads and validates an input file.

* `path` — path of the YAML input file. It's read as UTF-8; a byte order mark, which some editors add, is ignored.
* `read_history` — whether to read the previous schedules its [`history`](../input-format.md#history) lists, with
  [`read_schedule`](#read_schedulepath-schedule_input-readschedule), each with its own input, read with
  `read_history=False` (a history input's own history is never read). If false, `history` is left empty.

**Returns** a `ScheduleInput`. **Raises** `InputError` if the input is invalid, including if it isn't valid YAML,
or if a history entry's files can't be read or don't match.

### `parse_input(raw, directory=None, read_history=True)`

The same as `read_input`, for a document already loaded by `yaml.safe_load`. History paths are relative to
`directory` (the current directory if `None`).

## `validation` module

### `class InputError(ValueError)`

Invalid input. `problems` is a `tuple[str, ...]` with one message per problem, in input order; `str(error)` lists
them all. Each message says where the problem is, e.g.:

```
worker #3 ("Jeff"), likes: unknown worker "Jil"
post #1 ("front gate"), variation #2, time: is required
```

Positions are counted from 1, in the order entries appear in the file.

### `validate(schedule_input)`

Checks the rules that span several entries, raising `InputError` listing every violation:

* worker names are unique, and so are post names;
* no worker name contains `" & "` (`NAME_SEPARATOR`, which joins names in the [output](../output-format.md));
* every name in a worker's `likes` and `dislikes` is another existing worker, and no name is in both;
* a post's variations don't overlap;
* every history period ends by the time the schedule's period starts, and no two overlap.

### `find_problems(schedule_input)`

The same checks, returning the list of problem messages (empty if there are none) instead of raising.

### `history_warnings(schedule_input) -> list[str]`

Warnings about the history that don't stop a run: for each previous schedule with workers who aren't in this input,
one message naming them, e.g. `history entry #1 ("day1.yml"): "Dana" is not in this input; their history is
ignored`.

### `location(kind, index, name=None)`

Formats an entry's position for messages: `location("worker", 2, "Jeff")` is `worker #3 ("Jeff")`.

## `schedule_reader` module

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_schedule_reader.py`, on schedules written in every format).
> Used to read the previous schedules of an input's history
> ([ADR 0029](../../decisions/0029-schedule-history-input.md)), by the schedule audit, and by the tests.

Reads a written [schedule file](../output-format.md) back, given the input it was made for. Independent of the
`output` package: it relies only on the file's layout.

### `read_schedule(path, schedule_input) -> ReadSchedule`

* `path` — the schedule file. Its extension, in any case, gives the format: `.csv`, `.xlsx` or `.ods`.
* `schedule_input` — the [`ScheduleInput`](schedule-input.md) it was made for. Its shifts are generated as for any
  run, and each is read from the cell where it starts: the row whose start is the shift's start, in the column
  headed by its post's name. Since shift starts come from the input, consecutive shifts filled by the same workers
  are read apart in every format, even with a minimum rest of 0.

Formats:

* **CSV** — start times as ISO 8601 text; UTF-8, with or without a byte order mark (`CSV_READ_ENCODING`).
* **XLSX** — the first sheet; a merged cell's names are in its first cell.
* **ODS** — the first sheet; covered (merged) cells read as empty. Repeated rows and cells, which spreadsheets
  write for empty space, are expanded up to `ODS_REPEAT_LIMIT` (1000) times.

Spreadsheets saved again by another program (for example after editing by hand in LibreOffice or Excel) read the
same, as long as the layout is kept. Empty rows are skipped.

**Raises** `ScheduleReadError` (a `ValueError`) naming the problem: an unsupported format, a missing post column, no
row for a shift's start, a start that isn't a date and time, a shift with the wrong number of names, or an unknown
worker. `OSError` if the file can't be read.

### `class ReadSchedule(shifts, slots, assignment)`

Immutable. The shifts and slots generated from the input, in stable order, and `assignment`, a worker index per slot.
