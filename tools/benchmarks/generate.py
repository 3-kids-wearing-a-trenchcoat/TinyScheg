"""
Generate the benchmark inputs used to tune the scoring (docs/explanation/tuning.md): varied, mostly loose schedules
that branch and bound can solve. Deterministic: the same seeds always give the same inputs.
Usage: PYTHONPATH=src python tools/benchmarks/generate.py [--tier NAME ...] [--jobs N]
Candidates are tried in parallel, but taken in seed order, so the result doesn't depend on the number of jobs.
Writes tools/benchmarks/inputs/<name>.yml and tools/benchmarks/manifest.csv; existing inputs of a tier are replaced.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import multiprocessing
import os
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
SCARCE_HOLDERS = 3              # how many of the first workers have a scarce role
COMMON_SHARE = 0.5              # the share of the first workers who have a common role
ADDED_ROLE_CHANCE = 0.5         # the chance that a worker added to staff up has each role
AWAY_HOURS = (2, 4, 8)
DENSITY = {"sparse": (0.05, 0.03), "medium": (0.15, 0.08), "dense": (0.3, 0.15)}  # chance to like, to dislike
MIN_WITH_PREFERENCES = 2        # at least this many workers like or dislike someone (user requirement)
DESK_LENGTHS, PATROL_LENGTH = (4, 6), 4
NIGHT, DAY = "19:00-07:00", "08:00-20:00"
GATE_NIGHT_CHANCE = 0.7         # the gate needs a role holder and one more worker at night; otherwise 2 throughout
DESK_DAY_CHANCE = 0.5           # the desk is only open during the day
PATROL_CHANCE = 0.3             # a third post
PATROL_TIMES = ("06:00-18:00", "18:00-06:00")
FEASIBILITY_TIME_LIMIT = 5.0    # seconds to look for a legal schedule; proving there's none can take very long
HOLDOUT_EVERY = 3               # every third input of a tier is held back from tuning, to check the result
DEFAULT_JOBS = max(1, (os.cpu_count() or 2) - 2)  # candidates tried at once, leaving a little of the machine free
QUEUED_PER_JOB = 2              # candidates queued per job, so that jobs keep busy while an earlier seed is awaited


@dataclass(frozen=True, slots=True)
class Profile:
    """
    The knobs that differ between tiers: each role's scarcity (drawn from scarcity), the chance that a worker has a
    block of unavailability, the workers beyond the minimum staffing (drawn from slack) and the gate's shift lengths
    """
    scarcity: tuple[str, ...]
    away_chance: float
    slack: tuple[int, ...]
    gate_lengths: tuple[int, ...]


# many staff, few shifts each: one tight input in five, the rest with plenty of spare workers
STAFFED = Profile(scarcity=("common", "common", "common", "scarce"), away_chance=0.2, slack=(0, 2, 3, 4, 5),
                  gate_lengths=(3, 4))
# several shifts per worker, so that the audit has unevenness to see: short gate shifts, 1-2 spare workers, and
# choice coming from common roles and little unavailability rather than from a large staff
SHIFTS = Profile(scarcity=("common",), away_chance=0.1, slack=(1, 1, 2), gate_lengths=(2,))


@dataclass(frozen=True, slots=True)
class Tier:
    """A group of benchmarks: their length, how many, the first seed, how long branch and bound may take, and the
    knobs they're generated with."""
    name: str
    hours: tuple[int, ...]
    count: int
    first_seed: int
    time_limit: float
    profile: Profile


TIERS = {
    "sweep": Tier("sweep", (16, 20, 24), 12, 4000, 300.0, SHIFTS),
    "confirm": Tier("confirm", (24,), 3, 2000, 600.0, STAFFED),
    "multiday": Tier("multiday", (48,), 2, 3000, 600.0, STAFFED),
}


# --- generating one input ---

def generate(seed: int, hours: int, profile: Profile = STAFFED) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """
    Generate one input
    :param seed: int, the random seed
    :param hours: int, the schedule's length
    :param profile: Profile, the knobs that differ between tiers
    :return: (the input document, its knobs), or None if no legal schedule exists even with MAX_WORKERS
    """
    rng = random.Random(seed)
    start = dt.datetime(2025, 1, 1, rng.choice(START_HOURS))
    period = (start, start + dt.timedelta(hours=hours))
    posts = _posts(rng, profile)
    scarcity = {role: rng.choice(profile.scarcity) for role in ROLES}
    density = rng.choice(list(DENSITY))
    slack = rng.choice(profile.slack)
    first = NAMES[:MIN_WORKERS]
    holders = {role: set(rng.sample(first, SCARCE_HOLDERS if scarcity[role] == "scarce"
                                    else round(MIN_WORKERS * COMMON_SHARE))) for role in ROLES}
    workers = [_worker(rng, name, period, {role for role in ROLES if name in holders[role]}, profile.away_chance)
               for name in first]
    preference_seed = rng.randrange(2 ** 32)  # preferences are redrawn for every staffing, from the same seed

    def document() -> dict[str, Any]:
        return _document(period, _with_preferences(workers, density, preference_seed), posts)

    while not _has_legal_schedule(document()):
        if len(workers) == MAX_WORKERS:
            return None
        workers.append(_added_worker(rng, NAMES[len(workers)], period, profile.away_chance))
    minimum = len(workers)
    while len(workers) < min(minimum + slack, MAX_WORKERS):
        workers.append(_added_worker(rng, NAMES[len(workers)], period, profile.away_chance))
    knobs = {"seed": seed, "hours": hours, "start": start.strftime("%H:%M"), "workers": len(workers),
             "minimum_staff": minimum, "slack": len(workers) - minimum, "posts": len(posts),
             "medic": scarcity["medic"], "driver": scarcity["driver"], "preferences": density}
    return document(), knobs


def _posts(rng: random.Random, profile: Profile) -> list[dict[str, Any]]:
    """The posts: a gate with a shared shift, a desk needing a role, and sometimes a patrol of two."""
    gate: dict[str, Any] = {"name": "gate", "roles": {"any": 1}, "length": rng.choice(profile.gate_lengths)}
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


def _worker(rng: random.Random, name: str, period: tuple[dt.datetime, dt.datetime], roles: set[str],
            away_chance: float) -> dict[str, Any]:
    """A worker with the given roles, and with away_chance a block of unavailability within the period."""
    worker: dict[str, Any] = {"name": name, "roles": sorted(roles)}
    if rng.random() < away_chance:
        hours = int((period[1] - period[0]) / dt.timedelta(hours=1))
        away = period[0] + dt.timedelta(hours=rng.randrange(hours))
        worker["unavailable"] = [[away.isoformat(), (away + dt.timedelta(hours=rng.choice(AWAY_HOURS))).isoformat()]]
    return worker


def _added_worker(rng: random.Random, name: str, period: tuple[dt.datetime, dt.datetime],
                  away_chance: float) -> dict[str, Any]:
    """A worker added to staff up, with each role at ADDED_ROLE_CHANCE."""
    return _worker(rng, name, period, {role for role in ROLES if rng.random() < ADDED_ROLE_CHANCE}, away_chance)


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
    return _within(lambda: find_first_schedule(problem).assignment is not None, FEASIBILITY_TIME_LIMIT) is True


def _within(task: Any, limit: float) -> Any:
    """
    Run task, stopping it after limit seconds; a signal timer rather than a child process, since the candidates
    already run in pool workers, which can't start processes of their own
    :param task: a function taking no arguments
    :param limit: float, the time limit in seconds
    :return: what task returns, or None if it ran out of time
    """
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, limit)
    try:
        return task()
    except _TimedOut:
        return None
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


def solve_within(document: dict[str, Any], limit: float) -> tuple[float, float, int, int] | None:
    """solve_time, or None if branch and bound takes longer than limit seconds."""
    return _within(lambda: solve_time(document), limit)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One seed's outcome: the input generated (None if none has a legal schedule) and its solve (None if over the
    time limit, or not tried)."""
    seed: int
    hours: int
    generated: tuple[dict[str, Any], dict[str, Any]] | None
    solved: tuple[float, float, int, int] | None


def try_candidate(tier: Tier, seed: int) -> Candidate:
    """
    Generate one seed's input and solve it within the tier's time limit
    :param tier: Tier
    :param seed: int
    :return: Candidate
    """
    hours = tier.hours[seed % len(tier.hours)]
    generated = generate(seed, hours, tier.profile)
    if generated is None:
        return Candidate(seed, hours, None, None)
    check_requirements(generated[0])
    return Candidate(seed, hours, generated, solve_within(generated[0], tier.time_limit))


def write_input(path: pathlib.Path, document: dict[str, Any], knobs: dict[str, Any]) -> None:
    """Write an input as YAML, with its knobs in a comment at the top."""
    header = "# Benchmark input, generated by tools/benchmarks/generate.py: " + ", ".join(
        f"{key} {value}" for key, value in knobs.items()) + "\n"
    path.write_text(header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


def build_tier(tier: Tier, jobs: int = DEFAULT_JOBS) -> list[dict[str, Any]]:
    """
    Generate a tier's inputs, keeping only those branch and bound solves within the tier's time limit. Seeds are
    tried several at a time, but taken strictly in order, so the inputs kept are the same for any number of jobs.
    :param tier: Tier
    :param jobs: int, how many candidates are tried at once
    :return: a manifest row per input kept, and one per input skipped (with the reason)
    """
    rows: list[dict[str, Any]] = []
    kept = 0
    seeds = iter(range(tier.first_seed, tier.first_seed + 2 ** 31))
    with multiprocessing.Pool(jobs) as pool:  # leaving the block stops the candidates still running
        queued: collections.deque[Any] = collections.deque(
            pool.apply_async(try_candidate, (tier, next(seeds))) for _ in range(jobs * QUEUED_PER_JOB))
        while kept < tier.count:
            candidate: Candidate = queued.popleft().get()
            queued.append(pool.apply_async(try_candidate, (tier, next(seeds))))
            kept += _record(tier, candidate, kept, rows)
    return rows


def _record(tier: Tier, candidate: Candidate, kept: int, rows: list[dict[str, Any]]) -> int:
    """
    Add a candidate's manifest row, writing its input if it's kept
    :param tier: Tier
    :param candidate: Candidate
    :param kept: int, how many of the tier's inputs were kept before this one
    :param rows: the manifest rows so far, appended to
    :return: 1 if the candidate was kept, otherwise 0
    """
    if candidate.generated is None:
        rows.append({"name": "", "tier": tier.name, "seed": candidate.seed, "hours": candidate.hours,
                     "skipped": "no legal schedule even with the most workers"})
        return 0
    document, knobs = candidate.generated
    solved = candidate.solved
    if solved is None:
        rows.append({"name": "", "tier": tier.name, **knobs, "skipped": f"over {tier.time_limit:g} s"})
        print(f"{tier.name}: seed {knobs['seed']} skipped, over {tier.time_limit:g} s", flush=True)
        return 0
    seconds, penalty, slots, shared = solved
    name = f"{tier.name}_{kept + 1:02d}"
    write_input(INPUTS / f"{name}.yml", document, knobs)
    rows.append({"name": name, "tier": tier.name, **knobs, "holdout": (kept + 1) % HOLDOUT_EVERY == 0,
                 "slots": slots, "shared_slots": shared,
                 "slots_per_worker": round(slots / knobs["workers"], 2), "seconds": round(seconds, 2),
                 "default_penalty": round(penalty, 4), "skipped": ""})
    print(f"{tier.name}: {name} (seed {knobs['seed']}), {knobs['workers']} workers, {slots} slots, "
          f"{seconds:.1f} s", flush=True)
    return 1


MANIFEST_FIELDS = ("name", "tier", "holdout", "seed", "hours", "start", "workers", "minimum_staff", "slack", "posts",
                   "medic", "driver", "preferences", "slots", "shared_slots", "slots_per_worker", "seconds",
                   "default_penalty", "skipped")


def main() -> None:
    """Generate the tiers asked for (all by default), replacing their inputs and manifest rows."""
    parser = argparse.ArgumentParser(description="Generate the benchmark inputs.")
    parser.add_argument("--tier", action="append", choices=list(TIERS), help="a tier to generate (default: all)")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                        help=f"candidates tried at once (default {DEFAULT_JOBS})")
    arguments = parser.parse_args()
    if arguments.jobs < 1:
        parser.error("the number of jobs must be at least 1")
    names = arguments.tier or list(TIERS)
    INPUTS.mkdir(exist_ok=True)
    for name in names:
        for old in INPUTS.glob(f"{name}_*.yml"):
            old.unlink()
        write_manifest(name, build_tier(TIERS[name], arguments.jobs))


def write_manifest(tier_name: str, rows: list[dict[str, Any]]) -> None:
    """
    Replace one tier's rows in the manifest, as soon as the tier is done, so that a slow tier generated after it
    can't hold it back
    :param tier_name: str
    :param rows: the tier's new manifest rows
    """
    # the other tiers' rows are read only now, so that tiers generated at the same time don't overwrite each other
    kept_rows: list[dict[str, Any]] = []
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8", newline="") as file:
            kept_rows = [row for row in csv.DictReader(file) if row["tier"] != tier_name]
    with open(MANIFEST, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(kept_rows + rows)


if __name__ == "__main__":
    main()
