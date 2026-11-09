# Project: TinyScheg
TinyScheg is a shift scheduler meant to automate the creation of fair shift schedules for any group of workers.
Given a set of workers, a set of posts that need to be manned and a time period, it produces a schedule that satisfies
all hard constraints (availability, roles, minimum rest between shifts) while being as fair as possible and taking
workers' personal preferences into account.

The core approach is to treat scheduling as a **constraint satisfaction problem (CSP)** combined with a **scoring
(penalty) system** that quantifies how good a (partial) schedule is. The score is monotone along the search, which
allows pruning partial assignments that are guaranteed to be no better than the best complete schedule found so far.

Input is a YAML file (see `exampleInput.yml`), output is planned to be a CSV file.

## Project Status
* The project has been developed on-and-off over several years and through several iterations
  (an earlier Java version existed and was deleted from the repository on 2025-10-21).
  The current iteration is Python, started October 2025.
* The code is **partially implemented, has never been run end-to-end and contains known bugs.**
  Do not assume existing code is correct; when relying on a piece of existing code, verify it first.
* The design described below reflects the plans made so far. These plans are **open to revision** — they are a
  starting point, not a commitment.

## Internal Logic
Anything not mentioned in this section has yet to be decided on, this covers only the approaches settled on so far.
Items are marked **[implemented]** (exists in code, possibly buggy), **[partial]** or **[planned]**.

  ### Domain model
  * `DateTimeRange` (`src/DateTimeRange.py`) **[implemented]** — a half-open `[start, end)` range of timezone-naive
    datetimes, with comparison, overlap, padding and intersection helpers.
  * `Worker` (`src/Worker.py`) **[partial]** — name, roles, unavailability ranges, likes and dislikes.
    Workers are assumed available at all times except their explicit unavailability ranges.
    The role `"any"` (or `None`) is a wildcard every worker fulfills.
  * `Post` (`src/shift.py`) **[partial]** — a *template* for something that needs to be manned: required roles
    (role → number of workers), shift length, optional activity period and time-based *variations* that override
    these values (e.g. a night variation needing more workers). `gen_slot_list` splits a post over the schedule
    period into slots.
  * `Slot` (`src/shift.py`) **[partial]** — a single position for a single worker at a specific time.
    **Slots are the CSP variables** and **workers are the values**; each slot's domain is the set of workers that can
    fill it.
  * A **shift** is the group of slots belonging to the same post at the same time range (`Slot.same_shift`).

  ### Constraints
  * **Unary constraints** (availability, role) are applied when a `Slot` is constructed, pruning its domain.
  * **Binary "difference" constraints** connect any two slots that overlap in time or are less than the minimum rest
    period apart (`Slot.diff_constrained`) — the same worker cannot be assigned to both.

  ### Search
  * Backtracking search with **forward checking / constraint propagation** after each assignment.
  * Variable ordering: **MRV** (smallest domain first), with the **degree heuristic** (most constraints with
    unassigned slots) as tie-breaker (`Slot.csp_lt`).
  * Value ordering does not matter, since the search does not stop at the first solution.
  * **Branch and bound ("pocket")** **[planned]**: the best complete, legal schedule found so far is kept in a
    "pocket". Any partial assignment whose penalty is already worse than the pocket's is pruned, which is valid
    because penalty can only grow as more slots are assigned.
  * `Trail` **[planned]** — an undo stack. Each entry is the chain of actions caused by one assignment (the
    assignment itself, domain prunings, score changes), allowing backtracking to revert them exactly.
  * `Schedule` **[planned]** — holds the slots and the `Trail` and runs the search.

  ### Scoring
  * Fully specified in the Zettelkasten note `251028122014.md` ("Scoring - TinyScheg"), which is the spec for
    this part. The note itself has not been re-verified and may contain mistakes.
  * Summary: the total penalty is a weighted sum `a·L + b·W + c·R` (with `a + b + c = 1`) of three normalized
    components, each a sum of per-worker penalties:
    * **Likes/dislikes (`L`)** — penalty for sharing a shift with neutral workers (small) or disliked workers (large).
    * **Workload fairness (`W`)** — a convex, monotonically increasing function φ applied to each worker's workload
      ratio (assigned hours / available hours), so the sum is minimal when workloads are equal (Jensen's inequality).
    * **Rest deficit (`R`)** — how far each rest period falls short of a target proportional to the preceding
      shift's length, normalized by an upper bound on each worker's worst possible deficit.
  * `Scorer` **[planned]** — a per-worker object holding only what is needed to compute that worker's penalty.

  ### Input / Output
  * Input parsing from YAML **[planned]** — format documented by comments in `exampleInput.yml`.
  * Output to CSV **[planned]**.

## Knowledge Sources
Background and design notes live in the Zettelkasten at `/home/danny/Documents/Zettelkasten/`.
This folder contains many unrelated notes, as well as **stale notes from earlier iterations of TinyScheg**.
* **Current (Python iteration):**
  * `251021115839.md` — roadmap
  * `251021115817.md` — dev log
  * `251028122014.md` — scoring spec (the most important note)
  * `250226164306.md` — CSP course notes (Hebrew) the algorithm is based on
  * `250426143311.md` — "attempt 3" overview; its linked sub-pages are empty
* **Stale (Java iteration):** notes with IDs starting with `20250305` (`CSPState`, `Assessor`, `ShiftTemplate`, etc.).
  Do not treat them as describing the current design.
* When in doubt about whether a note is current, ask.
* The Zettelkasten is **read-only** — never modify it unless explicitly asked.
* A migration from the Zettelkasten into in-repo docs (which will become the source of truth) is planned but has not
  happened yet.

## Stack
The program is written in Python 3.13, using the Conda environment `tinyscheg` defined in `environment.yml`.
The only third-party dependency at this point is PyYAML.
New libraries should only be introduced under one of the following circumstances:
* A feature can't be implemented using the existing libraries.
* Implementing a feature with existing libraries would be less efficient.
* Implementing a feature with a new library would be "cleaner" in terms of readability.

If you want to add a new library or module, you must first explain to me why you want to do it, whether or not a
feature _could_ be implemented without introducing this new library and if so what implementing it with existing
libraries might look like.
You may only add this library or module after my explicit permission.
If you get this permission, make sure to also update `environment.yml` to reflect the change.

## Working rules
* Each modification to the code (be it changing, adding or deleting) must be briefly explained and applied only after
  my explicit permission.
* When editing, make the smallest change that solves the request.
* Do not rename files or reorganize directories unless asked.
* Commit changes you've made according to the Git Usage Rules outlined below.
* If you create new files under `/src`, add them to git.
* If something is ambiguous, inspect the existing code and follow its current patterns.
* If there is more than one sensible way to accomplish a task, offer both as options, list pros and cons for each
  approach, recommend one of these approaches and ask me which one to go with.
* Type hints required on all functions.
* Stick to PEP 8, with a 120 character line limit.
* Do not install Python packages yourself, I will handle that.
* Code should be readable. To that end:
  * Give variables meaningful names
  * Split long functions into smaller functions whenever practical
  * Add annotations at any point in which the code is not simple to understand
* Code should be split into sensible packages according to their domain and in a way that keeps dependency "flowing"
  in one direction.
  Ask me before creating a new package or moving a piece of logic from one package to another, and justify your request.
* Include docstrings. For simple functions and classes, one-line docstrings are enough.
  For non-trivial functions, docstrings should be of the following format:
  ```
  """
  Short description of the function
  :param x: specify what input parameter x is and what's its type
  (there should be one param line for each input parameter)
  :return: what this function returns
  """
  ```
* Use neutral, general-purpose scheduling language ("workers", "posts", "shifts") in code and documentation.
  TinyScheg is meant for any scheduling situation; don't tie it to a specific organization or domain.
* Leave TODO comments alone unless they're directly relevant to the task at hand.
* When a change affects the design described in this file (new classes, new logic, a planned item becoming
  implemented, a decision being revised), update the relevant section of this file as well.

## How to run
Always use `run.sh` to execute code. This is to make sure the correct Conda environment is used.
This script runs `conda run -n "$ENV_NAME" python "$@"`, so `run.sh` needs to be supplied only with the commands that
would appear after `python` if you were to write it manually (e.g. `./run.sh src/main.py`). `$ENV_NAME` is a constant
defined in the script and must match the name in `environment.yml`.
Modules in `src/` import each other by bare module name (e.g. `from DateTimeRange import ...`); `run.sh` adds `src/`
to `PYTHONPATH` so this works regardless of the working directory.
There is currently no test suite; how testing will be done is yet to be decided.

## Git Usage Rules
When working on this repository, you MUST follow these rules:

### Branching
* Work on the single existing branch that isn't `main`. Consolidate work onto that one working branch rather than
  juggling several in parallel.
* If no such branch exists (e.g. the previous one was merged and deleted), create a new one from `main`.
* If a branch exists and you are not sure whether you should use it or not, ask before continuing.
* Before applying git operations, make sure you're on the intended branch, as I may merge and delete branches and
  forget to notify you. If that happens, you may recreate the branch.
* NEVER work directly on `main`.

### Allowed Git Operations
You are allowed to:
* `git checkout -b <branch>` (if needed)
* `git checkout <branch>`
* `git add`
* `git commit`
* `git revert` (only for commits on your branch)
* `git merge <branch>` — LOCAL merges into your working branch only (e.g. consolidating another feature branch onto
  it). Never into `main`.

### Forbidden Git Operations
You are STRICTLY FORBIDDEN from:
* `git push`
* `git rebase`
* `git cherry-pick`
* `git pull` (unless explicitly instructed)
* Any operation that affects the `main` branch (including merging into it)

### Safety Rules
* Never delete branches.
* Never rewrite history (`rebase`, `commit --amend`, etc.).
* Only modify files relevant to the current task.
* Keep commits small and descriptive.

### Summary
You may make local commits, and local merges between feature branches, on your own working branch.
You may NEVER integrate your changes into `main` or interact with remotes.
