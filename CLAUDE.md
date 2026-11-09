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
* The design reflects the plans made so far. These plans are **open to revision** — they are a starting point, not a
  commitment.

## Documentation
The docs in `docs/` are the **source of truth** for TinyScheg's design. Start at `docs/index.md`.
They follow the [Diátaxis](https://diataxis.fr/) structure:
* `docs/how-to/` — task-oriented guides (e.g. development setup)
* `docs/reference/` — input/output formats and an API reference for every module in `src/`
* `docs/explanation/` — architecture, domain model, CSP formulation, search algorithm, scoring, glossary
* `docs/decisions/` — Architecture Decision Records (ADRs), one per design decision

Docs rules:
* The docs describe **intended** behaviour. Where code doesn't match the docs, that's a bug — don't "fix" the docs to
  match buggy code without asking.
* Every section describing behaviour carries an implementation-status alert (Implemented / Partially implemented /
  Not yet implemented, see the legend in `docs/index.md`). Keep these markers, and the status table in
  `docs/index.md`, accurate as code changes.
* When code changes add or change behaviour, update the relevant reference and explanation pages. This can be
  postponed until after the implementation has been made, verified and approved, but must not be forgotten.
* Record new design decisions as new ADRs. ADRs aren't edited after being accepted (other than their status); a
  changed decision gets a new ADR that supersedes the old one. See `docs/decisions/README.md`.
* The docs use GitHub-flavored Markdown, including GitHub alerts (`> [!NOTE]`), `$...$` / `$$...$$` math and
  Mermaid diagrams. In math, write `\lbrace` / `\rbrace` instead of `\{` / `\}`, which GitHub can mangle.
* `docs/explanation/scoring.md` was transferred as-is from the original notes, including a known mistake in the rest
  target formula. It will be reviewed separately; don't correct it unprompted.

## Knowledge Sources
The docs were migrated from notes in the Zettelkasten at `/home/danny/Documents/Zettelkasten/`, which are now
superseded by `docs/`. They may still be useful for background, but if they disagree with `docs/`, `docs/` wins.
* The Zettelkasten is **read-only** — never modify it unless explicitly asked.
* It contains many unrelated notes, as well as stale notes from earlier iterations of TinyScheg (notes with IDs
  starting with `20250305` describe the deleted Java version).

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
* If you create new files under `/src` or `/docs`, add them to git.
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

## How to run
Code is run with the `tinyscheg` Conda environment (`environment.yml`). I work with it activated
(`conda activate tinyscheg`) and run scripts with plain `python`.
Since your shell state does not persist between commands, activation won't carry over for you. Instead, always run
code through the environment explicitly: `conda run --no-capture-output -n tinyscheg python <args>`
(e.g. `conda run --no-capture-output -n tinyscheg python src/main.py`).
Modules in `src/` import each other by bare module name (e.g. `from DateTimeRange import ...`). Running a script inside
`src/` (e.g. `python src/main.py`) puts `src/` on the import path automatically; for anything else (such as
`python -c`), run from within `src/` or set `PYTHONPATH=src`.
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
