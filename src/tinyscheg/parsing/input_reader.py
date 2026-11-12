"""
Reading the YAML input into model objects.

Reading happens in two stages. First the structure of each entry is checked (required fields, types, values) while
converting it to model objects; then, if the structure is valid, the rules spanning several entries are checked
(see validation). Each stage reports every problem it finds at once, through an InputError.
"""
from __future__ import annotations

import datetime as dt
import math
import os
from collections.abc import Callable
from typing import Any, TypeVar

import yaml

from tinyscheg.model.post import Post, ShiftRules, Variation
from tinyscheg.model.schedule_input import DEFAULT_MIN_REST, ScheduleInput, ScoringParameters, Settings
from tinyscheg.model.worker import Worker
from tinyscheg.parsing.validation import InputError, location, validate
from tinyscheg.timing.daily_window import DailyWindow
from tinyscheg.timing.datetime_range import DateTimeRange, parse_range

T = TypeVar("T")

_TOP_LEVEL_FIELDS = {"settings", "workers", "posts"}
_SETTINGS_FIELDS = {"time", "min_rest", "scoring"}
_SCORING_FIELDS = {"weights", "workload_power", "rest_factor", "neutral_partner", "shift_share"}
_WEIGHT_FIELDS = {"likes", "workload", "rest"}
_WORKER_FIELDS = {"name", "roles", "unavailable", "likes", "dislikes"}
_POST_FIELDS = {"name", "roles", "length", "time", "variations"}
_VARIATION_FIELDS = {"time", "roles", "length"}


class _Failed(Exception):
    """Signals that converting an entry failed; its problems have already been recorded."""


def read_input(path: str | os.PathLike[str]) -> ScheduleInput:
    """
    Read and validate an input file
    :param path: path of the YAML input file (UTF-8)
    :return: ScheduleInput; raises InputError listing every problem if the input is invalid
    """
    # utf-8-sig also accepts files that some editors save with a byte order mark
    with open(path, encoding="utf-8-sig") as file:
        try:
            raw = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            raise InputError([f"not valid YAML: {exc}"]) from exc
    return parse_input(raw)


def parse_input(raw: object) -> ScheduleInput:
    """
    Convert loaded YAML into a validated ScheduleInput
    :param raw: the document as loaded by yaml.safe_load
    :return: ScheduleInput; raises InputError listing every problem if the input is invalid
    """
    problems: list[str] = []
    if not isinstance(raw, dict):
        raise InputError(["the input must be a mapping with the fields settings, workers and posts"])
    _check_fields(raw, _TOP_LEVEL_FIELDS, "the input", problems)
    settings = _attempt(problems, lambda: _parse_settings(raw, problems))
    workers = _parse_entries(raw, "workers", _parse_worker, problems)
    posts = _parse_entries(raw, "posts", _parse_post, problems)
    if problems:
        raise InputError(problems)
    schedule_input = ScheduleInput(settings, workers, posts)
    validate(schedule_input)
    return schedule_input


# --- entries ---

def _parse_settings(raw: dict[Any, Any], problems: list[str]) -> Settings:
    """Convert the settings section."""
    section = _required(raw, "settings", "the input", problems)
    if not isinstance(section, dict):
        problems.append("settings: must be a mapping")
        raise _Failed
    _check_fields(section, _SETTINGS_FIELDS, "settings", problems)
    period = _convert(problems, "settings, time", lambda: _date_time_range(_required_value(section, "time")))
    min_rest = _convert(problems, "settings, min_rest", lambda: _optional_hours(section, "min_rest", DEFAULT_MIN_REST))
    scoring = _attempt(problems, lambda: _parse_scoring(section.get("scoring"), problems))
    return _convert(problems, "settings", lambda: Settings(_ok(period), _ok(min_rest), _ok(scoring)))


def _parse_scoring(raw: object, problems: list[str]) -> ScoringParameters:
    """
    Convert the optional scoring section of the settings
    :param raw: the section as loaded, or None if it's omitted or empty
    :param problems: list to record problems in
    :return: ScoringParameters; omitted fields (and omitted weights) keep their defaults
    """
    if raw is None:
        return ScoringParameters()
    where = "settings, scoring"
    section = _entry_mapping(raw, where, _SCORING_FIELDS, problems)
    overrides: dict[str, Any] = {}
    weights = section.get("weights")
    if weights is not None:
        weights = _entry_mapping(weights, f"{where}, weights", _WEIGHT_FIELDS, problems)
        for name in sorted(_WEIGHT_FIELDS & weights.keys()):
            if weights[name] is not None:
                overrides[f"{name}_weight"] = weights[name]
    for name in sorted(_SCORING_FIELDS - {"weights"}):
        if section.get(name) is not None:
            overrides[name] = section[name]
    # ScoringParameters checks the values, naming the field in its message. Checking each one on its own (the others
    # at their defaults) reports every invalid field rather than only the first; then they're checked together.
    checked = [_convert(problems, where, lambda: ScoringParameters(**{name: value}))
               for name, value in overrides.items()]
    if any(parameters is None for parameters in checked):
        raise _Failed
    return _ok(_convert(problems, where, lambda: ScoringParameters(**overrides)))


def _parse_worker(raw: object, index: int, problems: list[str]) -> Worker:
    """Convert one worker entry, the index-th in the list."""
    where = location("worker", index)
    entry = _entry_mapping(raw, where, _WORKER_FIELDS, problems)
    name = _convert(problems, f"{where}, name", lambda: _string(_required_value(entry, "name")))
    where = location("worker", index, name)
    roles = _convert(problems, f"{where}, roles", lambda: frozenset(_string_list(entry.get("roles"))))
    unavailable = _convert(problems, f"{where}, unavailable", lambda: tuple(_range_list(entry.get("unavailable"))))
    likes = _convert(problems, f"{where}, likes", lambda: frozenset(_string_list(entry.get("likes"))))
    dislikes = _convert(problems, f"{where}, dislikes", lambda: frozenset(_string_list(entry.get("dislikes"))))
    return Worker(_ok(name), _ok(roles), _ok(unavailable), _ok(likes), _ok(dislikes))


def _parse_post(raw: object, index: int, problems: list[str]) -> Post:
    """Convert one post entry, the index-th in the list, filling in its variations' fields from the general case."""
    where = location("post", index)
    entry = _entry_mapping(raw, where, _POST_FIELDS, problems)
    name = _convert(problems, f"{where}, name", lambda: _string(_required_value(entry, "name")))
    where = location("post", index, name)
    length = _convert(problems, f"{where}, length", lambda: _hours(_required_value(entry, "length"), positive=True))
    roles = _convert(problems, f"{where}, roles", lambda: _role_counts(_required_value(entry, "roles")))
    window = _convert(problems, f"{where}, time", lambda: _optional_window(entry.get("time")))
    rules = _convert(problems, where, lambda: ShiftRules(_ok(length), _ok(roles)))
    variations = []
    raw_variations = _convert(problems, f"{where}, variations", lambda: _optional_list(entry.get("variations")))
    for variation_index, raw_variation in enumerate(raw_variations or []):
        variation_where = f"{where}, variation #{variation_index + 1}"
        variations.append(_attempt(problems, lambda: _parse_variation(raw_variation, variation_where, rules,
                                                                      problems)))
    return Post(_ok(name), _ok(rules), window, tuple(_ok(variation) for variation in variations))


def _parse_variation(raw: object, where: str, general: ShiftRules | None, problems: list[str]) -> Variation:
    """Convert one variation; any field it doesn't specify is inherited from general (None if that failed)."""
    entry = _entry_mapping(raw, where, _VARIATION_FIELDS, problems)
    window = _convert(problems, f"{where}, time", lambda: DailyWindow.parse(_required_value(entry, "time")))
    length = _convert(problems, f"{where}, length",
                      lambda: None if entry.get("length") is None else _hours(entry["length"], positive=True))
    roles = _convert(problems, f"{where}, roles",
                     lambda: None if entry.get("roles") is None else _role_counts(entry["roles"]))
    if general is None:  # the post's own rules are invalid, so there's nothing to inherit from
        raise _Failed
    rules = _convert(problems, where, lambda: ShiftRules(general.length if length is None else length,
                                                         general.roles if roles is None else roles))
    return Variation(_ok(window), _ok(rules))


# --- collecting problems ---

def _parse_entries(raw: dict[Any, Any], field: str,
                   parse_entry: Callable[[object, int, list[str]], T], problems: list[str]) -> tuple[T, ...]:
    """
    Convert a required, non-empty list of entries, recording problems for each entry separately
    :param raw: the input mapping
    :param field: str, the list's field name, e.g. "workers"
    :param parse_entry: function converting one entry, given the entry, its 0-based index and the problem list
    :param problems: list to record problems in
    :return: the converted entries (incomplete if any failed)
    """
    entries = _attempt(problems, lambda: _required(raw, field, "the input", problems))
    if entries is None:
        return ()
    if not isinstance(entries, list) or not entries:
        problems.append(f"{field}: must be a non-empty list")
        return ()
    converted = (_attempt(problems, lambda: parse_entry(entry, index, problems))
                 for index, entry in enumerate(entries))
    return tuple(entry for entry in converted if entry is not None)


def _attempt(problems: list[str], build: Callable[[], T]) -> T | None:
    """Run build, returning None instead if it fails after recording its problems."""
    try:
        return build()
    except _Failed:
        return None


def _convert(problems: list[str], where: str, convert: Callable[[], T]) -> T | None:
    """
    Run one conversion, recording its error as a problem instead of raising it
    :param problems: list to record problems in
    :param where: str, location of the converted value, prefixed to the error message
    :param convert: function doing the conversion; raises TypeError or ValueError for invalid values
    :return: the converted value, or None if it failed (or depended on a value that failed)
    """
    try:
        return convert()
    except _Failed:
        return None
    except (TypeError, ValueError) as exc:
        problems.append(f"{where}: {exc}")
        return None


def _ok(value: T | None) -> T:
    """Return value, or stop building the current entry if it's None (its conversion failed)."""
    if value is None:
        raise _Failed
    return value


def _check_fields(entry: dict[Any, Any], allowed: set[str], where: str, problems: list[str]) -> None:
    """Record a problem for each field not in allowed (usually a typo, which would otherwise go unnoticed)."""
    for field in entry:
        if field not in allowed:
            problems.append(f"{where}: unknown field {field!r} (expected one of: {', '.join(sorted(allowed))})")


def _entry_mapping(raw: object, where: str, allowed: set[str], problems: list[str]) -> dict[Any, Any]:
    """Check that an entry is a mapping with only allowed fields, and return it."""
    if not isinstance(raw, dict):
        problems.append(f"{where}: must be a mapping of fields")
        raise _Failed
    _check_fields(raw, allowed, where, problems)
    return raw


def _required(entry: dict[Any, Any], field: str, where: str, problems: list[str]) -> Any:
    """Return a required field, recording a problem if it's missing or empty."""
    if entry.get(field) is None:
        problems.append(f"{where}: missing required field {field!r}")
        raise _Failed
    return entry[field]


# --- values ---

def _required_value(entry: dict[Any, Any], field: str) -> Any:
    """Return a required field's value, raising ValueError if it's missing or empty."""
    if entry.get(field) is None:
        raise ValueError("is required")
    return entry[field]


def _string(value: object) -> str:
    """Check that value is a string."""
    if not isinstance(value, str):
        raise TypeError(f"must be a string, got {value!r}")
    return value


def _optional_list(value: object) -> list[Any]:
    """An optional list: None (left empty) means an empty list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"must be a list, got {value!r}")
    return value


def _string_list(value: object) -> list[str]:
    """An optional list of strings."""
    items = _optional_list(value)
    for item in items:
        if not isinstance(item, str):
            raise TypeError(f"must be a list of strings, got {item!r} in it")
    return items


def _date_time_range(value: object) -> DateTimeRange:
    """
    Convert a pair of date-times to a DateTimeRange
    :param value: a pair of ISO 8601 strings. Unquoted dates and date-times, which YAML loads as date or datetime
    objects, are accepted too.
    :return: DateTimeRange
    """
    if isinstance(value, list):
        value = [_iso_text(item) for item in value]
    return parse_range(value)


def _iso_text(value: object) -> object:
    """Turn a date or datetime loaded by YAML back into ISO 8601 text; leave anything else as it is."""
    if isinstance(value, (dt.date, dt.datetime)):  # datetime is a subclass of date
        return value.isoformat()
    return value


def _range_list(value: object) -> list[DateTimeRange]:
    """An optional list of date-time ranges, naming the position of any invalid range."""
    ranges = []
    for index, item in enumerate(_optional_list(value)):
        try:
            ranges.append(_date_time_range(item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"range #{index + 1}: {exc}") from exc
    return ranges


def _hours(value: object, positive: bool) -> dt.timedelta:
    """
    Convert a number of hours to a timedelta
    :param value: int or float
    :param positive: bool, True to require more than 0, False to require at least 0
    :return: datetime.timedelta
    """
    # bool is a subclass of int, but `true` isn't a number of hours
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TypeError(f"must be a number of hours, got {value!r}")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"must be {'more than' if positive else 'at least'} 0 hours, got {value!r}")
    return dt.timedelta(hours=value)


def _optional_hours(entry: dict[Any, Any], field: str, default: dt.timedelta) -> dt.timedelta:
    """An optional, non-negative number of hours."""
    if entry.get(field) is None:
        return default
    return _hours(entry[field], positive=False)


def _optional_window(value: object) -> DailyWindow | None:
    """An optional daily window; None means the post is always active."""
    return None if value is None else DailyWindow.parse(value)


def _role_counts(value: object) -> tuple[tuple[str, int], ...]:
    """A mapping of role names to the number of workers needed, in input order."""
    if not isinstance(value, dict):
        raise TypeError(f"must be a mapping of role names to numbers of workers, got {value!r}")
    for role, count in value.items():
        if not isinstance(role, str):
            raise TypeError(f"role names must be strings, got {role!r}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"the count for role {role!r} must be a whole number of at least 0, got {count!r}")
    return tuple(value.items())
