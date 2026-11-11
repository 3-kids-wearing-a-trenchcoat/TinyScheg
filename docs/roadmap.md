# Roadmap

The work left to make TinyScheg produce fair schedules, in the order it's planned. Each step links to the design it
implements. Component status is in the [status table](index.md#implementation-status); ideas that aren't scheduled
yet are described in [Future work](explanation/future-work.md).

When something is deferred, it goes both into [Later](#later) here and into
[Future work](explanation/future-work.md).

Progress: Phase 1 — 4 of 7 steps done.

## Phase 1: Walking skeleton

Input to *a* legal schedule (not yet the best one), written as CSV, end to end.
Done when `python src/main.py exampleInput.yml -o schedule.csv` produces a schedule that an independent checker
confirms meets every hard constraint.

- [x] **1. `DateTimeRange`** — immutable, half-open ranges ([reference](reference/api/datetime-range.md))
- [x] **2. Input parsing and validation** ([input format](reference/input-format.md))
    - [x] `DailyWindow`, `Worker`, `Post`, `ShiftRules`, `Variation`, `Settings`, `ScheduleInput`
    - [x] YAML reading, with all problems reported together
    - [x] Cross-entry validation (unique names, preference references, overlapping variations, `" & "` in names)
- [x] **3. Shift generation by segments** ([ADR 0018](decisions/0018-slot-generation-by-segments.md))
    - [x] Immutable `Shift` and `Slot`, in stable order
    - [x] Segments, back-to-back shifts, dangling last shift, closing a post with a zero-worker variation
- [x] **4. CSP setup** — `csp/problem.py` ([CSP formulation](explanation/csp-formulation.md))
    - [x] Initial domains (availability, role), with workers by index
    - [x] Difference constraints (overlap, minimum rest)
    - [x] Detecting slots no worker can fill
- [ ] **5. Search state and plain backtracking** — `csp/state.py`, `csp/search.py`
  ([ADR 0016](decisions/0016-undo-through-change-records-on-the-call-stack.md))
    - [ ] Explicit search state: domains and assignments
    - [ ] Change records, undone on backtracking
    - [ ] Backtracking to the first legal schedule, slots in stable order
    - [ ] Tracking the deepest point reached, for reporting infeasibility
      ([ADR 0020](decisions/0020-report-where-infeasibility-was-found.md))
- [ ] **6. Grid output, CSV** — `output/grid.py`, `output/csv_writer.py`
  ([ADR 0019](decisions/0019-output-as-a-time-by-post-grid.md))
    - [ ] Assigned slots → time-by-post grid (rows between shift boundaries, names joined with `" & "`)
    - [ ] CSV writer (UTF-8 with BOM, ISO 8601 times)
- [ ] **7. Command line and end-to-end test** — `cli.py`, `src/main.py`
    - [ ] `python src/main.py input.yml -o schedule.csv`; output format chosen by file extension
    - [ ] Reporting invalid input
    - [ ] Reporting infeasible input on the command line, with no output file: the unfillable slots, or where the
      search got stuck ([ADR 0011](decisions/0011-no-output-for-infeasible-inputs.md),
      [ADR 0020](decisions/0020-report-where-infeasibility-was-found.md))
    - [ ] Independent hard-constraint checker for tests (`tests/schedule_checker.py`)
    - [ ] End-to-end test on `exampleInput.yml`

## Phase 2: Efficient search

Same result as phase 1, found with far less work.

- [ ] Forward checking, recorded in change records
  ([ADR 0017](decisions/0017-plain-forward-checking-and-pruning-on-ties.md))
- [ ] Variable ordering: MRV, then degree, then stable order
  ([ADR 0003](decisions/0003-variable-ordering-mrv-degree.md))
- [ ] Tests: the same schedules as plain backtracking, and determinism

## Phase 3: Scoring

A penalty score for any (partial) schedule, computed from scratch ([Scoring](explanation/scoring.md)).

- [ ] Decide the open points: φ ($x^p$ or $e^{ax}-1$), parameter and weight values, whether they're set in the input
- [ ] Constants: each worker's availability, the number of shared slots, worst rest deficit, packable maximum
- [ ] Workload penalty ([ADR 0013](decisions/0013-availability-weighted-workload.md),
  [ADR 0015](decisions/0015-normalize-workload-by-packable-maximum.md))
- [ ] Rest penalty ([ADR 0014](decisions/0014-exact-worst-rest-deficit.md))
- [ ] Likes/dislikes penalty
- [ ] Weighted sum of normalized penalties ([ADR 0005](decisions/0005-weighted-sum-of-normalized-penalties.md))
- [ ] Property tests: monotone along the search, path-independent and deterministic
  ([ADR 0012](decisions/0012-deterministic-path-independent-scoring.md))

## Phase 4: Branch and bound

The *best* legal schedule ([ADR 0004](decisions/0004-branch-and-bound-with-monotone-penalty.md)).

- [ ] Search all solutions, keeping the best in the pocket
- [ ] Prune branches whose score is already at least the pocket's (ties included)
- [ ] Tests: same result as brute force on small inputs

## Phase 5: Spreadsheet output

([Output format](reference/output-format.md))

- [ ] XLSX writer (openpyxl), multi-row shifts as merged cells
- [ ] ODS writer (odfpy), multi-row shifts as merged cells

## Phase 6: Schedule history

Extending a previous schedule rather than starting fresh ([Future work](explanation/future-work.md#schedule-history)).

- [ ] Read a previous output grid (CSV, XLSX or ODS) back as fixed assignments
- [ ] Minimum rest across the boundary between schedules
- [ ] Fairness carried over between consecutive schedules
- [ ] Resolve the CSV read-back limitation with a minimum rest of 0

## Later

Not scheduled; see [Future work](explanation/future-work.md) for each.

- [ ] Incremental scoring, exactly path-independent
- [ ] Faster search: cheapest-first value order, symmetry breaking, a stronger lower bound, a time limit
- [ ] Explaining more fully why an input is infeasible
- [ ] Handling dangling shifts (keep, merge, or set a minimum length)
- [ ] Time and post preferences
- [ ] Right-to-left spreadsheets
- [ ] Docs: tutorials, generated API reference, publishing the site
- [ ] An optional graphical interface, for people who don't use the command line
- [ ] Distribution as a single executable (command line or GUI) for Windows and Linux, possibly macOS
