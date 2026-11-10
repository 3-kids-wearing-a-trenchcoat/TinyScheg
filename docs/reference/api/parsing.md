# `parsing` package

Sources: [`src/tinyscheg/parsing/input_reader.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/parsing/input_reader.py) and
[`src/tinyscheg/parsing/validation.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/parsing/validation.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_input_reader.py`, `tests/test_validation.py`).

Reads the [input file](../input-format.md) into a [`ScheduleInput`](schedule-input.md), in two stages:

1. **Structure:** each entry is checked (required fields, unknown fields, types and values) while it's converted to
   model objects. This includes filling in each variation's unspecified fields from its post.
2. **Validation:** if the structure is valid, the rules that span several entries are checked.

Each stage reports **every** problem it finds at once. The second stage only runs once the first finds none, so
that problems aren't reported twice (e.g. a "like" naming a worker whose own entry was invalid).

## `input_reader` module

### `read_input(path)`

Reads and validates an input file.

* `path` — path of the YAML input file. It's read as UTF-8; a byte order mark, which some editors add, is ignored.

**Returns** a `ScheduleInput`. **Raises** `InputError` if the input is invalid, including if it isn't valid YAML.

### `parse_input(raw)`

The same as `read_input`, for a document already loaded by `yaml.safe_load`.

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
* a post's variations don't overlap.

### `find_problems(schedule_input)`

The same checks, returning the list of problem messages (empty if there are none) instead of raising.

### `location(kind, index, name=None)`

Formats an entry's position for messages: `location("worker", 2, "Jeff")` is `worker #3 ("Jeff")`.
