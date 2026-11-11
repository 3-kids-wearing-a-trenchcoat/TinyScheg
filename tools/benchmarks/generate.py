"""
Generate the benchmark inputs used to tune the scoring (docs/explanation/tuning.md): varied, mostly loose schedules
that branch and bound can solve. Deterministic: the same seeds always give the same inputs.
Usage: PYTHONPATH=src python tools/benchmarks/generate.py [--tier NAME ...]
Writes tools/benchmarks/inputs/<name>.yml and tools/benchmarks/manifest.csv; existing inputs of a tier are replaced.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import multiprocessing
import pathlib
import random
import signal
import time
from dataclasses import dataclass
from typing import Any

import yaml

from tinyscheg.csp.problem import build_problem, unfillable_slots
from tinyscheg.csp.search import find_best_schedule, find_first_schedule
from tinyscheg.parsing.input_reader import parse_input
from tinyscheg.scoring.constants import build_constants

BENCHMARKS = pathlib.Path(__file__).parent
INPUTS = BENCHMARKS / "inputs"
MANIFEST = BENCHMARKS / "manifest.csv"

NAMES = ("Avery", "Blake", "Casey", "Drew", "Emery", "Finley", "Gray", "Harper", "Indy", "Jules", "Kai", "Logan")
ROLES = ("medic", "driver")
MIN_WORKERS = 6                 # every benchmark has at least this many workers (user requirement)
MAX_WORKERS = len(NAMES)
MIN_REST = 6                    # hours; generally not lower (user)
START_HOURS = (0, 8, 16)        # the time of day a schedule starts
SCARCITY = ("common", "common", "common", "scarce")  # each role is common three times in four
SCARCE_HOLDERS = 3              # how many of the first workers have a scarce role
COMMON_SHARE = 0.5              # the share of the first workers who have a common role
ADDED_ROLE_CHANCE = 0.5         # the chance that a worker added to staff up has each role
AWAY_CHANCE = 0.2               # the chance that a worker has a block of unavailability
AWAY_HOURS = (2, 4, 8)
DENSITY = {"sparse": (0.05, 0.03), "medium": (0.15, 0.08), "dense": (0.3, 0.15)}  # chance to like, to dislike
MIN_WITH_PREFERENCES = 2        # at least this many workers like or dislike someone (user requirement)
SLACK = (0, 2, 3, 4, 5)         # workers beyond the minimum staffing: one tight input in five, the rest loose
GATE_LENGTHS, DESK_LENGTHS, PATROL_LENGTH = (3, 4), (4, 6), 4
NIGHT, DAY = "19:00-07:00", "08:00-20:00"
GATE_NIGHT_CHANCE = 0.7         # the gate needs a role holder and one more worker at night; otherwise 2 throughout
DESK_DAY_CHANCE = 0.5           # the desk is only open during the day
PATROL_CHANCE = 0.3             # a third post
PATROL_TIMES = ("06:00-18:00", "18:00-06:00")
FEASIBILITY_TIME_LIMIT = 5.0    # seconds to look for a legal schedule; proving there's none can take very long
HOLDOUT_EVERY = 3               # every third input of a tier is held back from tuning, to check the result


@dataclass(frozen=True, slots=True)
class Tier:
    """A group of benchmarks: their length, how many, the first seed, and how long branch and bound may take."""
    name: str
    hours: tuple[int, ...]
    count: int
    first_seed: int
    time_limit: float


TIERS = {
    "sweep": Tier("sweep", (12, 16), 12, 1000, 30.0),
    "confirm": Tier("confirm", (24,), 3, 2000, 600.0),
    "multiday": Tier("multiday", (48,), 2, 3000, 600.0),
}


# --- generating one input ---

def generate(seed: int, hours: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """
    Generate one input
    :param seed: int, the random seed
    :param hours: int, the schedule's length
    :return: (the input document, its knobs), or None if no legal schedule exists even with MAX_WORKERS
    """
    rng = random.Random(seed)
    start = dt.datetime(2025, 1, 1, rng.choice(START_HOURS))
    period = (start, start + dt.timedelta(hours=hours))
    posts = _posts(rng)
    scarcity = {role: rng.choice(SCARCITY) for role in ROLES}
    density = rng.choice(list(DENSITY))
    slack = rng.choice(SLACK)
    first = NAMES[:MIN_WORKERS]
    holders = {role: set(rng.sample(first, SCARCE_HOLDERS if scarcity[role] == "scarce"
                                    else round(MIN_WORKERS * COMMON_SHARE))) for role in ROLES}
    workers = [_worker(rng, name, period, {role for role in ROLES if name in holders[role]}) for name in first]
    preference_seed = rng.randrange(2 ** 32)  # preferences are redrawn for every staffing, from the same seed

    def document() -> dict[str, Any]:
        return _document(period, _with_preferences(workers, density, preference_seed), posts)

    while not _has_legal_schedule(document()):
        if len(workers) == MAX_WORKERS:
            return None
        workers.append(_added_worker(rng, NAMES[len(workers)], period))
    minimum = len(workers)
    while len(workers) < min(minimum + slack, MAX_WORKERS):
        workers.append(_added_worker(rng, NAMES[len(workers)], period))
    knobs = {"seed": seed, "hours": hours, "start": start.strftime("%H:%M"), "workers": len(workers),
             "minimum_staff": minimum, "slack": len(workers) - minimum, "posts": len(posts),
             "medic": scarcity["medic"], "driver": scarcity["driver"], "preferences": density}
    return document(), knobs


def _posts(rng: random.Random) -> list[dict[str, Any]]:
    """The posts: a gate with a shared shift, a desk needing a role, and sometimes a patrol of two."""
    gate: dict[str, Any] = {"name": "gate", "roles": {"any": 1}, "length": rng.choice(GATE_LENGTHS)}
    if rng.random() < GATE_NIGHT_CHANCE:
        gate["variations"] = [{"time": NIGHT, "roles": {rng.choice(ROLES): 1, "any": 1}}]
    else:
        gate["roles"] = {"any": 2}
    desk: dict[str, Any] = {"name": "desk", "roles": {rng.choice(ROLES): 1}, "length": rng.choice(DESK_LENGTHS)}
    if rng.random() < DESK_DAY_CHANCE:
        desk["time"] = DAY
    posts = [gate, desk]
    if rng.random() < PATROL_CHANCE:
        posts.append({"name": "patrol", "roles": {"any": 2}, "length": PATROL_LENGTH,
                      "time": rng.choice(PATROL_TIMES)})
    return posts


def _worker(rng: random.Random, name: str, period: tuple[dt.datetime, dt.datetime],
            roles: set[str]) -> dict[str, Any]:
    """A worker with the given roles, and with AWAY_CHANCE a block of unavailability within the period."""
    worker: dict[str, Any] = {"name": name, "roles": sorted(roles)}
    if rng.random() < AWAY_CHANCE:
        hours = int((period[1] - period[0]) / dt.timedelta(hours=1))
        away = period[0] + dt.timedelta(hours=rng.randrange(hours))
        worker["unavailable"] = [[away.isoformat(), (away + dt.timedelta(hours=rng.choice(AWAY_HOURS))).isoformat()]]
    return worker


def _added_worker(rng: random.Random, name: str, period: tuple[dt.datetime, dt.datetime]) -> dict[str, Any]:
    """A worker added to staff up, with each role at ADDED_ROLE_CHANCE."""
    return _worker(rng, name, period, {role for role in ROLES if rng.random() < ADDED_ROLE_CHANCE})


def _with_preferences(workers: list[dict[str, Any]], density: str, seed: int) -> list[dict[str, Any]]:
    """
    The workers with likes and dislikes drawn at the given density, and at least MIN_WITH_PREFERENCES of them with
    some
    """
    rng = random.Random(seed)
    like_chance, dislike_chance = DENSITY[density]
    names = [worker["name"] for worker in workers]
    result = []
    for worker in workers:
        others = [name for name in names if name != worker["name"]]
        likes = [name for name in others if rng.random() < like_chance]
        dislikes = [name for name in others if name not in likes and rng.random() < dislike_chance]
        result.append({**worker, "likes": likes, "dislikes": dislikes})
    while sum(1 for worker in result if worker["likes"] or worker["dislikes"]) < MIN_WITH_PREFERENCES:
        worker = rng.choice([worker for worker in result if not worker["likes"] and not worker["dislikes"]])
        worker["likes"].append(rng.choice([name for name in names if name != worker["name"]]))
    return result


def _document(period: tuple[dt.datetime, dt.datetime], workers: list[dict[str, Any]],
              posts: list[dict[str, Any]]) -> dict[str, Any]:
    """An input document, as it's written to YAML."""
    return {"settings": {"time": [moment.isoformat() for moment in period], "min_rest": MIN_REST},
            "workers": workers, "posts": posts}


class _TimedOut(Exception):
    """A search went over its time limit."""


def _on_alarm(signum: int, frame: Any) -> None:
    """Stop a search that went over its time limit."""
    raise _TimedOut


def _has_legal_schedule(document: dict[str, Any]) -> bool:
    """
    True if a legal schedule was found within FEASIBILITY_TIME_LIMIT; an input whose search runs out of time is
    treated as having none, so that it gets another worker
    """
    problem = build_problem(parse_input(document))
    if unfillable_slots(problem):
        return False
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, FEASIBILITY_TIME_LIMIT)
    try:
        return find_first_schedule(problem).assignment is not None
    except _TimedOut:
        return False
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def check_requirements(document: dict[str, Any]) -> None:
    """Raise AssertionError unless the input meets every benchmark requirement (see the tuning docs)."""
    assert len(document["posts"]) >= 2, "at least 2 posts"
    assert len(document["workers"]) >= MIN_WORKERS, f"at least {MIN_WORKERS} workers"
    assert any(sum(post["roles"].values()) > 1 or any(sum(variation["roles"].values()) > 1
                                                      for variation in post.get("variations", ()))
               for post in document["posts"]), "a post with more than one worker some of the time"
    assert sum(1 for worker in document["workers"]
               if worker["likes"] or worker["dislikes"]) >= MIN_WITH_PREFERENCES, "workers with preferences"


# --- accepting inputs ---

def solve_time(document: dict[str, Any]) -> tuple[float, float, int, int]:
    """
    Run branch and bound on an input at the default parameters
    :return: (seconds, penalty, slots, shared slots)
    """
    schedule_input = parse_input(document)
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.domains)
    started = time.perf_counter()
    result = find_best_schedule(problem, constants)
    assert result.penalty is not None
    return time.perf_counter() - started, result.penalty.total, len(problem.slots), constants.shared_slots


def _solve_in_child(document: dict[str, Any], results: Any) -> None:
    """Solve in a child process, so that a search over the time limit can be stopped."""
    results.put(solve_time(document))


def solve_within(document: dict[str, Any], limit: float) -> tuple[float, float, int, int] | None:
    """solve_time, or None if branch and bound takes longer than limit seconds."""
    results: Any = multiprocessing.Queue()
    child = multiprocessing.Process(target=_solve_in_child, args=(document, results))
    child.start()
    child.join(limit)
    if child.is_alive():
        child.terminate()
        child.join()
        return None
    return results.get()


def write_input(path: pathlib.Path, document: dict[str, Any], knobs: dict[str, Any]) -> None:
    """Write an input as YAML, with its knobs in a comment at the top."""
    header = "# Benchmark input, generated by tools/benchmarks/generate.py: " + ", ".join(
        f"{key} {value}" for key, value in knobs.items()) + "\n"
    path.write_text(header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


def build_tier(tier: Tier) -> list[dict[str, Any]]:
    """
    Generate a tier's inputs, keeping only those branch and bound solves within the tier's time limit
    :return: a manifest row per input kept, and one per input skipped (with the reason)
    """
    rows: list[dict[str, Any]] = []
    seed, kept = tier.first_seed, 0
    while kept < tier.count:
        hours = tier.hours[seed % len(tier.hours)]
        generated = generate(seed, hours)
        seed += 1
        if generated is None:
            rows.append({"name": "", "tier": tier.name, "seed": seed - 1, "hours": hours,
                         "skipped": "no legal schedule even with the most workers"})
            continue
        document, knobs = generated
        check_requirements(document)
        solved = solve_within(document, tier.time_limit)
        if solved is None:
            rows.append({"name": "", "tier": tier.name, **knobs, "skipped": f"over {tier.time_limit:g} s"})
            print(f"{tier.name}: seed {knobs['seed']} skipped, over {tier.time_limit:g} s", flush=True)
            continue
        seconds, penalty, slots, shared = solved
        name = f"{tier.name}_{kept + 1:02d}"
        write_input(INPUTS / f"{name}.yml", document, knobs)
        rows.append({"name": name, "tier": tier.name, **knobs, "holdout": (kept + 1) % HOLDOUT_EVERY == 0,
                     "slots": slots, "shared_slots": shared, "seconds": round(seconds, 2),
                     "default_penalty": round(penalty, 4), "skipped": ""})
        print(f"{tier.name}: {name} (seed {knobs['seed']}), {knobs['workers']} workers, {slots} slots, "
              f"{seconds:.1f} s", flush=True)
        kept += 1
    return rows


MANIFEST_FIELDS = ("name", "tier", "holdout", "seed", "hours", "start", "workers", "minimum_staff", "slack", "posts",
                   "medic", "driver", "preferences", "slots", "shared_slots", "seconds", "default_penalty", "skipped")


def main() -> None:
    """Generate the tiers asked for (all by default), replacing their inputs and manifest rows."""
    parser = argparse.ArgumentParser(description="Generate the benchmark inputs.")
    parser.add_argument("--tier", action="append", choices=list(TIERS), help="a tier to generate (default: all)")
    names = parser.parse_args().tier or list(TIERS)
    INPUTS.mkdir(exist_ok=True)
    new_rows: list[dict[str, Any]] = []
    for name in names:
        for old in INPUTS.glob(f"{name}_*.yml"):
            old.unlink()
        new_rows += build_tier(TIERS[name])
    # read the other tiers' rows only now, so that tiers generated at the same time don't overwrite each other
    kept_rows: list[dict[str, Any]] = []
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8", newline="") as file:
            kept_rows = [row for row in csv.DictReader(file) if row["tier"] not in names]
    kept_rows += new_rows
    with open(MANIFEST, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(kept_rows)


if __name__ == "__main__":
    main()
