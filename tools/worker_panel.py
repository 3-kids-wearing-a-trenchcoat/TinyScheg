"""
The worker panel (ADR 0052): a language model plays each worker of a schedule, reading it as published and writing
down what they would complain about, as a check on the schedule audit. Development only: it runs headless Claude Code
(`claude -p`) on the account in use, with no API key and nothing installed.

Each worker sees facts, with no thresholds or targets: how the workplace works, the schedule as a grid of numbered
shifts, who is away when, roles, every worker's hours and rests, and their own profile (only their own likes and
dislikes). The part every worker of a schedule shares goes in the system prompt, so that each worker after the first
reads it from the cache; the worker's own profile is the message.

Schedules come from a tuning stage's results (tools/tune.py), named <input>-first (the first period) or <input>-both
(the second period, with the first as its history).
Usage (from the repository root):
  PYTHONPATH=src python tools/worker_panel.py write OUT SCHEDULE [SCHEDULE ...] [--stage STAGE]
      write each schedule's input files to OUT/inputs/
  PYTHONPATH=src python tools/worker_panel.py run OUT RUN SCHEDULE [SCHEDULE ...] [--model MODEL] [--sample N]
                                                  [--seed SEED] [--dry-run]
      run the workers (every one, or N drawn at random per schedule) and write their answers and each one's tokens
      and cost to OUT/answers/RUN/
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import random
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence

import audit
import tune
from tinyscheg.csp.problem import build_problem
from tinyscheg.model.shift import Shift
from tinyscheg.model.schedule_input import ScheduleInput
from tinyscheg.model.worker import ANY_ROLE
from tinyscheg.parsing.input_reader import read_input

DEFAULT_STAGE = "next-period"
DEFAULT_MODEL = "sonnet"
EFFORT = "low"
SAMPLE_PER_SCHEDULE = 4  # a routine check (ADR 0052): enough to catch every finding seen 7 times or more in 174 workers
TIMEOUT_SECONDS = 600
FIXED_EMPTY_FOLDER = pathlib.Path(tempfile.gettempdir()) / "tinyscheg-worker-panel"
FIRST, BOTH = "first", "both"
USAGE_FIELDS = ("schedule", "worker", "model", "input", "cache_write", "cache_read", "output", "thinking", "cost_usd",
                "seconds", "complaints")
SYSTEM_PROMPT = """\
You are one of the workers on a shift schedule that has just been published. The workplace and the schedule are \
described below; the message names you.

Read the schedule as this worker would, and write down each thing about your own schedule that you would complain \
about to whoever made it.
Raise what you would actually raise. If you would have nothing to say, answer with an empty list.

Answer with only a JSON list, one entry per complaint:
- "complaint": the complaint, in your own words
- "shifts": the shifts it's about, by their numbers in the schedule
- "people": the coworkers it involves, if any
- "avoidable": whether you think it could have been avoided: "yes", "no" or "not sure"
"""


# --- the input: what a worker sees ---

def short_time(moment: dt.datetime) -> str:
    """A moment as shown to the workers, e.g. 'Jan 1 16:00'."""
    return f"{moment:%b} {moment.day} {moment:%H:%M}"


def hours_text(value: float) -> str:
    """Hours as shown to the workers, e.g. '6 h' or '2.5 h'."""
    return f"{round(value, 2):g} h"


def numbering(context: audit.AuditContext) -> dict[int, int]:
    """Each shift's number as shown (1, 2, ...), in time order, then post order."""
    posts = [post.name for post in context.schedule_input.posts]
    ordered = sorted(range(len(context.shifts)),
                     key=lambda s: (context.shifts[s].time.start, posts.index(context.shifts[s].post.name)))
    return {shift: position + 1 for position, shift in enumerate(ordered)}


def workplace(schedule_input: ScheduleInput) -> list[str]:
    """How the workplace works: what every worker knows. No minimum rest and no even share (ADR 0052)."""
    lines = ["## How this workplace works", "",
             "- Every slot of every shift below must be filled.",
             "- Shifts are a duty: everyone would rather work less, not more.",
             "- Work is shared in proportion to availability: someone available half as long is expected to work half "
             "as many hours. Availability counts only the hours when at least one post is staffed.",
             "- Some slots need a role; only workers with that role can take them.",
             "- People work together only with the others on the same shift, not with those at other posts.",
             "- Every hour counts the same, whatever the time of day."]
    if schedule_input.history:
        start = short_time(schedule_input.settings.period.start)
        lines.append(f"- This schedule continues a previous one. Shifts before {start} were already worked and can't "
                     f"change; the new schedule starts at {start}. Time between the two schedules isn't rest or work "
                     f"for anyone.")
    return lines + [""]


def role_of_slots(shift: Shift) -> str:
    """The roles a shift's slots need, e.g. '2 slots: 1 driver, 1 any role'."""
    roles = [slot.role for slot in shift.slots]
    parts = [f"{roles.count(role)} {'any role' if role == ANY_ROLE else role}" for role in dict.fromkeys(roles)]
    return f"{len(roles)} slot{'s' if len(roles) > 1 else ''}: {', '.join(parts)}"


def post_header(context: audit.AuditContext, post: str) -> str:
    """A post's column header: its name, and its slots if every shift of the post has the same."""
    kinds = {role_of_slots(shift) for shift in context.shifts if shift.post.name == post}
    return f"{post} ({kinds.pop()})" if len(kinds) == 1 else post


def schedule_grid(context: audit.AuditContext, crews: Sequence[Sequence[int]], names: Sequence[str],
                  number: dict[int, int]) -> list[str]:
    """
    The schedule as a grid: a row per interval between shift boundaries (intervals with no shift left out), a column
    per post, each shift shown where it starts, with its number and crew (and its slots, where a post's shifts differ)
    :param context: AuditContext
    :param crews: the workers of each shift
    :param names: the workers' names
    :param number: each shift's number as shown
    :return: the section's lines
    """
    posts = [post.name for post in context.schedule_input.posts]
    headers = [post_header(context, post) for post in posts]
    bounds = sorted({moment for shift in context.shifts for moment in (shift.time.start, shift.time.end)})
    lines = ["## The schedule", "",
             "Each cell shows the shift number and who works it; \"(cont.)\" means the shift above goes on.", "",
             "| time | " + " | ".join(headers) + " |", "|---|" + "---|" * len(posts)]
    for start, end in zip(bounds, bounds[1:]):
        cells, active = [], False
        for post, header in zip(posts, headers):
            shift = next((s for s in range(len(context.shifts)) if context.shifts[s].post.name == post
                          and context.shifts[s].time.start <= start and context.shifts[s].time.end >= end), None)
            if shift is None:
                cells.append("")
            elif context.shifts[shift].time.start == start:
                active = True
                slots = "" if header != post else f" ({role_of_slots(context.shifts[shift])})"
                cells.append(f"#{number[shift]} " + " & ".join(names[w] for w in crews[shift]) + slots)
            else:
                active = True
                cells.append(f"(cont. #{number[shift]})")
        if active:
            lines.append(f"| {short_time(start)}-{end:%H:%M} | " + " | ".join(cells) + " |")
    return lines + [""]


def away_and_roles(context: audit.AuditContext, schedule_input: ScheduleInput, names: Sequence[str]) -> list[str]:
    """
    Who is away when (the time between schedules left out: the rules say it once), which roles each worker has, and
    per role the slots needing it and who has it
    :param context: AuditContext
    :param schedule_input: ScheduleInput (with its history, if any)
    :param names: the workers' names
    :return: the sections' lines
    """
    start = min(shift.time.start for shift in context.shifts)
    end = max(shift.time.end for shift in context.shifts)
    periods = sorted([p.schedule_input.settings.period for p in schedule_input.history]
                     + [schedule_input.settings.period], key=lambda period: period.start)
    gaps = [(earlier.end, later.start) for earlier, later in zip(periods, periods[1:]) if later.start > earlier.end]
    lines = ["## Who is away when", ""]
    for index, name in enumerate(names):
        pieces = [(max(a.start, start), min(a.end, end))
                  for a in context.away[index] if a.end > start and a.start < end]
        for gap_start, gap_end in gaps:
            pieces = [part for a, b in pieces
                      for part in ((a, min(b, gap_start)), (max(a, gap_end), b)) if part[1] > part[0]]
        if pieces:
            lines.append(f"- {name}: " + "; ".join(f"{short_time(a)} to {short_time(b)}" for a, b in pieces))
    if len(lines) == 2:
        lines.append("Nobody is away during the schedule.")
    lines += ["", "## Roles", ""]
    for worker in schedule_input.workers:
        lines.append(f"- {worker.name}: " + (", ".join(sorted(worker.roles)) or "no role"))
    for role in sorted({slot.role for slot in context.slots} - {ANY_ROLE}):
        slots = [slot for slot in context.slots if slot.role == role]
        holders = [w.name for w in schedule_input.workers if w.has_role(role)]
        hours = math.fsum(slot.time.duration / dt.timedelta(hours=1) for slot in slots)
        lines.append(f"- Slots needing {role}: {len(slots)} ({hours_text(hours)}); workers with {role}: "
                     + ", ".join(holders))
    return lines + [""]


def everyone(context: audit.AuditContext, crews: Sequence[Sequence[int]], names: Sequence[str],
             number: dict[int, int]) -> list[str]:
    """
    Every worker's facts: hours available and worked, the share of their available time worked, their shifts (each
    with its length; the grid shows who with) and rests
    :param context: AuditContext
    :param crews: the workers of each shift
    :param names: the workers' names
    :param number: each shift's number as shown
    :return: the sections' lines
    """
    facts = [audit.worker_facts(context, crews, w) for w in range(len(names))]
    lines = ["## Every worker's hours", "",
             "| worker | available | worked | share of available time worked | shifts |", "|---|---|---|---|---|"]
    for name, f in zip(names, facts):
        share = f"{f.hours / f.availability:.0%}" if f.availability else "-"
        lines.append(f"| {name} | {hours_text(f.availability)} | {hours_text(f.hours)} | {share} | {len(f.shifts)} |")
    lines += ["", "## Every worker's shifts and rests", ""]
    for name, f in zip(names, facts):
        shifts = ", ".join(f"#{number[s]} ({hours_text(audit.shift_hours(context, s))})" for s in f.shifts)
        lines.append(f"- {name}: {shifts or 'no shifts'}")
        for rest in f.rests:
            gap = (context.shifts[rest.after].time.start - context.shifts[rest.before].time.end) / dt.timedelta(hours=1)
            away = gap - rest.hours
            lines.append(f"  - rest between #{number[rest.before]} and #{number[rest.after]}: {hours_text(gap)}"
                         + (f", of which {hours_text(away)} away or between schedules" if away > audit.EPSILON else ""))
    return lines + [""]


def shared_text(context: audit.AuditContext, assignment: tuple[int, ...], schedule_input: ScheduleInput) -> str:
    """
    What every worker of a schedule sees: the workplace, the grid, absences, roles, and everyone's hours and rests
    :param context: AuditContext of the schedule (with a history, the whole schedule)
    :param assignment: a worker index per slot (of the whole schedule)
    :param schedule_input: ScheduleInput
    :return: the text, in Markdown
    """
    crews = audit.workers_by_shift(context, assignment)
    names = [w.name for w in schedule_input.workers]
    number = numbering(context)
    return "\n".join(["# A published shift schedule", ""] + workplace(schedule_input)
                     + schedule_grid(context, crews, names, number) + away_and_roles(context, schedule_input, names)
                     + everyone(context, crews, names, number))


def profile_text(schedule_input: ScheduleInput, worker_name: str) -> str:
    """The worker's own profile, the message: their roles, likes and dislikes (nobody else's preferences)."""
    worker = next(w for w in schedule_input.workers if w.name == worker_name)
    return "\n".join(["## You", "",
                      f"You are {worker.name}.",
                      f"- Your roles: {', '.join(sorted(worker.roles)) or 'none'}",
                      f"- People you like working with: {', '.join(sorted(worker.likes)) or 'nobody in particular'}",
                      "- People you'd rather not work with: "
                      + (", ".join(sorted(worker.dislikes)) or "nobody in particular"), ""])


def load_schedule(stage: str, label: str) -> tuple[audit.AuditContext, tuple[int, ...], ScheduleInput]:
    """
    A schedule from a tuning stage's results
    :param stage: the stage, e.g. next-period
    :param label: <input>-first for the first period, <input>-both for the second (with the first as its history)
    :return: (the AuditContext, the assignment it audits, the ScheduleInput)
    """
    name, period = label.rsplit("-", 1)
    if period not in (FIRST, BOTH):
        raise ValueError(f"{label}: a schedule is named <input>-{FIRST} or <input>-{BOTH}")
    with open(tune.results_path(stage), encoding="utf-8") as file:
        row = next((r for r in csv.DictReader(file) if r["input"] == name), None)
    if row is None:
        raise ValueError(f"{name} isn't in the results of stage {stage}")
    schedule_input = read_input(tune.Benchmark(row["input"], row["tier"], row["holdout"] == "True").path)
    assignment = tuple(int(w) for w in row["assignment"].split())
    if period == BOTH:
        schedule_input = tune.next_period(schedule_input, assignment)
        assignment = tuple(int(w) for w in row["day2_assignment"].split())
    context, whole = tune.audit_context(schedule_input, build_problem(schedule_input), assignment)
    return context, whole, schedule_input


def write_inputs(out: pathlib.Path, stage: str, label: str) -> list[pathlib.Path]:
    """Write a schedule's input files: <label>.md, what everyone sees, and <label>-<worker>.md, each worker's own."""
    context, assignment, schedule_input = load_schedule(stage, label)
    folder = out / "inputs"
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / f"{label}.md"]
    paths[0].write_text(shared_text(context, assignment, schedule_input), encoding="utf-8")
    for worker in schedule_input.workers:
        paths.append(folder / f"{label}-{worker.name}.md")
        paths[-1].write_text(profile_text(schedule_input, worker.name), encoding="utf-8")
    return paths


# --- running the workers ---

def claude_command(model: str, system_prompt: str) -> list[str]:
    """The headless command: the given system prompt only, with no tools, MCP servers, settings or saved session."""
    return ["claude", "-p", "--model", model, "--effort", EFFORT, "--system-prompt", system_prompt,
            "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "",
            "--no-session-persistence", "--output-format", "json"]


def parse_answer(text: str) -> list | None:
    """The worker's JSON list from their reply (code fences allowed), or None if there isn't one."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        answer = json.loads(body)
    except json.JSONDecodeError:
        return None
    return answer if isinstance(answer, list) else None


def schedule_workers(out: pathlib.Path, label: str) -> list[str]:
    """The workers of a schedule whose input files were written, by name."""
    shared = out / "inputs" / f"{label}.md"
    if not shared.exists():
        raise FileNotFoundError(f"no input for {label}: run `worker_panel.py write {out} {label}` first")
    return sorted(path.stem[len(label) + 1:] for path in shared.parent.glob(f"{label}-*.md"))


def draw_workers(names: Sequence[str], count: int | None, rng: random.Random) -> list[str]:
    """Every worker if count is None or covers them all, else `count` of them drawn at random, in their order."""
    if count is None or count >= len(names):
        return list(names)
    chosen = set(rng.sample(list(names), count))
    return [name for name in names if name in chosen]


def run_one(out: pathlib.Path, run: str, model: str, label: str, worker: str) -> dict:
    """
    Run one worker, from the fixed empty folder, and save their answer (the raw reply as .txt if it isn't a JSON list)
    :param out: the panel's folder
    :param run: the run's name, its folder under answers/
    :param model: the model, e.g. sonnet
    :param label: the schedule
    :param worker: the worker's name
    :return: the run's row for usage.csv
    """
    system = SYSTEM_PROMPT + "\n" + (out / "inputs" / f"{label}.md").read_text(encoding="utf-8")
    message = (out / "inputs" / f"{label}-{worker}.md").read_text(encoding="utf-8")
    finished = subprocess.run(claude_command(model, system), input=message, capture_output=True, text=True,
                              cwd=FIXED_EMPTY_FOLDER, timeout=TIMEOUT_SECONDS, check=True)
    result = json.loads(finished.stdout)
    usage = result["usage"]
    answers = out / "answers" / run
    answer = parse_answer(result.get("result", ""))
    if answer is None:
        (answers / f"{label}-{worker}.txt").write_text(result.get("result", ""), encoding="utf-8")
    else:
        (answers / f"{label}-{worker}.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
    return {"schedule": label, "worker": worker, "model": ",".join(result.get("modelUsage", {})) or model,
            "input": usage["input_tokens"], "cache_write": usage["cache_creation_input_tokens"],
            "cache_read": usage["cache_read_input_tokens"], "output": usage["output_tokens"],
            "thinking": usage.get("output_tokens_details", {}).get("thinking_tokens", 0),
            "cost_usd": round(result.get("total_cost_usd", 0.0), 5), "seconds": round(result["duration_ms"] / 1000, 1),
            "complaints": "malformed" if answer is None else len(answer)}


def run_panel(out: pathlib.Path, run: str, labels: Sequence[str], model: str, sample: int | None, seed: int,
              dry_run: bool) -> None:
    """
    Run the workers of each schedule, one after another (so that each after the first reads the shared part from the
    cache), appending each one's tokens and cost to answers/<run>/usage.csv
    :param out: the panel's folder
    :param run: the run's name
    :param labels: the schedules
    :param model: the model
    :param sample: workers drawn at random per schedule, or None for every worker
    :param seed: the seed of the draw
    :param dry_run: only print who would run and how much text each would send
    """
    rng = random.Random(seed)
    pairs = [(label, name) for label in labels for name in draw_workers(schedule_workers(out, label), sample, rng)]
    if dry_run:
        for label, name in pairs:
            shared = (out / "inputs" / f"{label}.md").read_text(encoding="utf-8")
            message = (out / "inputs" / f"{label}-{name}.md").read_text(encoding="utf-8")
            print(f"{label} {name}: system prompt {len(SYSTEM_PROMPT) + 1 + len(shared)} chars, "
                  f"message {len(message)} chars")
        print(f"{len(pairs)} workers")
        return
    FIXED_EMPTY_FOLDER.mkdir(exist_ok=True)
    if any(FIXED_EMPTY_FOLDER.iterdir()):
        sys.exit(f"{FIXED_EMPTY_FOLDER} isn't empty: claude must run from an empty folder")
    answers = out / "answers" / run
    answers.mkdir(parents=True, exist_ok=True)
    usage_path = answers / "usage.csv"
    new_file = not usage_path.exists()
    started = time.time()
    with open(usage_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=USAGE_FIELDS)
        if new_file:
            writer.writeheader()
        for label, name in pairs:
            row = run_one(out, run, model, label, name)
            writer.writerow(row)
            file.flush()
            print(" ".join(f"{key}={row[key]}" for key in USAGE_FIELDS))
    print(f"{len(pairs)} workers in {time.time() - started:.0f} s")


def main(arguments: Sequence[str] | None = None) -> None:
    """The command line: write inputs, or run the workers."""
    parser = argparse.ArgumentParser(description="The worker panel (ADR 0052): a check on the schedule audit.")
    commands = parser.add_subparsers(dest="command", required=True)
    write = commands.add_parser("write", help="write each schedule's input files to OUT/inputs/")
    write.add_argument("out", type=pathlib.Path)
    write.add_argument("schedules", nargs="+")
    write.add_argument("--stage", default=DEFAULT_STAGE)
    run = commands.add_parser("run", help="run the workers; answers and usage go to OUT/answers/RUN/")
    run.add_argument("out", type=pathlib.Path)
    run.add_argument("run")
    run.add_argument("schedules", nargs="+")
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--sample", type=int, nargs="?", const=SAMPLE_PER_SCHEDULE, default=None,
                     help=f"workers drawn at random per schedule ({SAMPLE_PER_SCHEDULE} if no number is given)")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(arguments)
    if args.command == "write":
        for label in args.schedules:
            print(*write_inputs(args.out, args.stage, label), sep="\n")
    else:
        run_panel(args.out, args.run, args.schedules, args.model, args.sample, args.seed, args.dry_run)


if __name__ == "__main__":
    main()
