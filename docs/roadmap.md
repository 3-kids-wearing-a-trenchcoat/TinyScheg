# Roadmap

The work left to make TinyScheg produce fair schedules, in the order it's planned. Each step links to the design it
implements. Component status is in the [status table](index.md#implementation-status); ideas that aren't scheduled
yet are described in [Future work](explanation/future-work.md).

When something is deferred, it goes both into [Later](#later) here and into
[Future work](explanation/future-work.md).

Progress: Phases 1–7 complete; the penalty's parts made flat after Phase 7 ([ADR 0032](decisions/0032-flat-penalty-parts.md)); PyPy for development runs ([ADR 0033](decisions/0033-pypy-for-development-runs.md)); never back to back ([ADR 0034](decisions/0034-never-back-to-back.md)). Phase 8 in progress.

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
- [x] **5. Search state and backtracking with forward checking** — `csp/state.py`, `csp/search.py`
  ([ADR 0016](decisions/0016-undo-through-change-records-on-the-call-stack.md),
  [ADR 0017](decisions/0017-plain-forward-checking-and-pruning-on-ties.md))
    - [x] Explicit search state: domains and assignments
    - [x] Forward checking, recorded in change records, undone on backtracking
    - [x] Backtracking to the first legal schedule, slots in stable order
    - [x] Tracking the deepest point reached, for reporting infeasibility
      ([ADR 0020](decisions/0020-report-where-infeasibility-was-found.md))
    - [x] Independent hard-constraint checker for tests (now `tools/schedule_checker.py`)
- [x] **6. Grid output, CSV** — `output/grid.py`, `output/csv_writer.py`
  ([ADR 0019](decisions/0019-output-as-a-time-by-post-grid.md))
    - [x] Assigned slots → time-by-post grid (rows between shift boundaries, names joined with `" & "`), each cell
      holding its covering shift
    - [x] CSV writer (UTF-8 with BOM, ISO 8601 times)
- [x] **7. Command line and end-to-end test** — `cli.py`, `src/main.py`, `output/writers.py`
  ([Command line](reference/command-line.md))
    - [x] `python src/main.py input.yml -o schedule.csv`; output format chosen by file extension; without `-o`,
      `<input name>_schedule.csv` next to the input
    - [x] Reporting invalid input
    - [x] Reporting infeasible input on the command line, with no output file: the unfillable slots, or where the
      search got stuck ([ADR 0011](decisions/0011-no-output-for-infeasible-inputs.md),
      [ADR 0020](decisions/0020-report-where-infeasibility-was-found.md))
    - [x] End-to-end test on `exampleInput.yml`, checking the written file independently

## Phase 2: Scoring

A penalty score for any (partial) schedule, computed from scratch ([Scoring](explanation/scoring.md)). Scoring is a
pure function of a (partial) assignment, so it's built and tested on fixed assignments, independently of the search.

- [x] Confirm the formulas as corrected in the 2026-11-10 review, and decide the open points: φ ($x^p$ or
  $e^{ax}-1$), parameter and weight values, whether they're set in the input
  ([ADR 0021](decisions/0021-power-function-for-workload-fairness.md),
  [ADR 0022](decisions/0022-scoring-parameters-with-defaults-and-input-overrides.md))
- [x] Scoring parameters: defaults as named constants, and the optional `scoring` input settings (parsing,
  validation)
- [x] Constants: each worker's availability, the number of shared slots, worst rest deficit, packable maximum
- [x] Workload penalty ([ADR 0013](decisions/0013-availability-weighted-workload.md),
  [ADR 0015](decisions/0015-normalize-workload-by-packable-maximum.md))
- [x] Rest penalty ([ADR 0014](decisions/0014-exact-worst-rest-deficit.md))
- [x] Likes/dislikes penalty
- [x] Weighted sum of normalized penalties ([ADR 0005](decisions/0005-weighted-sum-of-normalized-penalties.md))
- [x] Property tests: monotone along the search, path-independent and deterministic
  ([ADR 0012](decisions/0012-deterministic-path-independent-scoring.md))
- [x] Show the written schedule's penalty on the command line

## Phase 3: Efficient search

Legal schedules found with far less work, before branch and bound multiplies the search. (Forward checking was
brought forward into step 5.)

- [x] Variable ordering: MRV, then degree, then stable order
  ([ADR 0003](decisions/0003-variable-ordering-mrv-degree.md))
- [x] With scoring in place, decide whether any scoring-based speedups (cheapest-first value order, a stronger
  lower bound; see [Later](#later)) are needed before branch and bound. **Not yet:** with MRV, finding a legal
  schedule or proving there is none is instant at our sizes; whether branch and bound needs them can only be
  measured in phase 5, so they stay in Later, to be reconsidered there
- [x] Tests: legal schedules (checked independently) on the same inputs, infeasibility still found, and determinism

## Phase 4: Schedule audit (development tool)

An independent "audit" of a finished schedule from each worker's point of view, to check that the scoring and its
tuning don't produce undesirable behaviour such as concentrated unfairness. For development and analysis only: it
lives in `tools/`, outside the `tinyscheg` package, reads the written schedule file and the input, and shares no
code with `csp/` or `scoring/`.

- [x] Spec: the criteria and their definitions, for approval before any code
  ([Schedule audit](explanation/schedule-audit.md)). Judged **relative to other workers**: excess over the most
  even split possible (in any 24 hours and overall), easy fixes (could a few simple legal swaps or moves fix it?), how
  often each worker draws the short straw, and social pairings
- [x] Move the independent hard-constraint checker from `tests/` to `tools/`, shared by the tests and the audit,
  with a reader for written CSV schedules (since moved into the package, see Phase 7)
- [x] Per-worker feedback cards and a group summary of how concentrated the unfairness is
- [x] Sampling: many legal schedules (by shuffling the workers' order), each audited and shown next to its internal
  penalty, flagging where the two disagree
- [x] Tests for the audit itself, and a how-to page ([Auditing a schedule](how-to/audit-a-schedule.md))

## Phase 5: Branch and bound

The *best* legal schedule ([ADR 0004](decisions/0004-branch-and-bound-with-monotone-penalty.md)).

- [x] Search all solutions, keeping the best in the pocket (`find_best_schedule`)
- [x] Prune branches whose score is already at least the pocket's (ties included)
- [x] Tests: same result as brute force on small inputs
- [x] Measure the search on the example, and decide on the scoring-based speedups in [Later](#later) (and a time
  limit) that it needs. **None for now:** get it working first. The search runs to the end with no limit (about
  3–4 minutes for 24 hours; 48 hours and more much longer) and can be interrupted with Ctrl+C; the measurements are
  in [Future work](explanation/future-work.md#search-performance). (Revisited during tuning, below: the 24-hour
  example now takes about 10 seconds; 48 hours is still out of reach.)
- [x] Use branch and bound on the command line, reporting each better schedule found as it goes; the example is
  now 24 hours long, so that it finishes
- [x] Check that no simple legal swap lowers the chosen schedule's penalty: no single legal move or swap beats branch
  and bound's schedule, tested on 12- and 14-hour versions of the example and checked once on the 24-hour one
- [x] Tune the scoring parameters with the audit ([Tuning the scoring](explanation/tuning.md))
    - [x] Plan, priorities and benchmark requirements
    - [x] Benchmark generator and tuning runner (`tools/benchmarks/generate.py`, `tools/tune.py`)
    - [x] Speed up branch and bound enough for informative benchmarks: cheapest-first value order and a lower bound
      on workload ([ADR 0024](decisions/0024-cheapest-first-value-order-and-workload-bound.md)), interchangeable
      slots in order ([ADR 0025](decisions/0025-order-interchangeable-slots.md)), look-ahead bounds for likes and
      workload, and incremental scoring ([ADR 0027](decisions/0027-incremental-scoring-for-steering.md))
    - [x] Baseline at the defaults, and diagnosis of each complaint with an easy fix
    - [x] Corrections the baseline showed were needed: in the audit, heaviest day dropped, liked partners counted
      apart, short rest relative to the schedule's own norm, and a day as any 24 hours rather than a calendar day
      ([Schedule audit](explanation/schedule-audit.md)); in the scoring, workload counting shifts as well as hours
      ([ADR 0026](decisions/0026-workload-counts-shifts-and-hours.md))
    - [x] Sensitivity, one parameter at a time
    - [x] Rounds by hand: a few candidate settings at a time (`tools/tune.py round`)
    - [x] Choose and check the defaults (held-back inputs, the confirm tier, cards read by hand): rest factor 2.5
      ([ADR 0028](decisions/0028-rest-factor-default-2-5.md)). The 48-hour tier is out of the search's reach for now

## Phase 6: Spreadsheet output

([Output format](reference/output-format.md))

- [x] XLSX writer (openpyxl), multi-row shifts as merged cells
- [x] ODS writer (odfpy), multi-row shifts as merged cells

## Phase 7: Schedule history

Extending previous schedules rather than starting fresh ([Future work](explanation/future-work.md#schedule-history)).

- [x] Design: previous inputs and their schedule files, read back as fixed history
  ([ADR 0029](decisions/0029-schedule-history-input.md)), scored together with the new schedule
  ([ADR 0030](decisions/0030-history-in-scoring.md))
- [x] Schedule reader in the package (`parsing/schedule_reader.py`): CSV, XLSX and ODS, each shift read where it
  starts, which also resolves the CSV read-back limitation with a minimum rest of 0; the development tools use it
- [x] The `history` input section: parsing, validation (periods before the current one and not overlapping), a
  warning for workers who have left
- [x] The history as the already-filled first part of one schedule
  ([ADR 0031](decisions/0031-history-as-the-filled-part-of-one-schedule.md)): history slots fixed, the minimum rest
  across the boundary from the ordinary constraints, availability over the whole schedule, scoring and incremental
  scoring from scratch on the filled part; the independent checker covers the boundary
- [x] Command line: the new period written, the whole schedule's penalty reported, a warning for workers who have
  left
- [x] Audit across schedules: the audit reads the history too, to check that fairness carries over, including
  whether past short straws need compensating (ADR 0030)
- [x] End-to-end test: two consecutive schedules, the second making up for the first

## Phase 8: Progress, then rest and availability

Following a long search, then the rest part's blind spots found on 2026-11-13 and 2026-11-14.

- [ ] **Search progress and Ctrl+C** ([ADR 0035](decisions/0035-search-progress-and-keeping-the-best-on-interrupt.md))
    - [x] The share of the search space finished, tracked by the search, which only observes
    - [x] Command line: a two-line block redrawn in place on a terminal (the best schedule so far, and the progress
      with a rough time left); plain lines otherwise
    - [x] Ctrl+C writes the best schedule found so far, marked as not proven the best
- [ ] **Rest targets derived from the input** (prototypes in progress): a target after each shift proportional to its
  length, by the schedule's own ratio of free time to work, instead of a rest factor chosen by hand
- [ ] **Each worker's worst rest deficit from scratch over the history:** a history slot counts for everyone who was
  available for it and had its role that day, not only for whoever worked it
- [ ] **Rests measured in available time:** unavailable time inside a rest counts as neither work nor rest
- [ ] Re-check the weights against the corrected audit

## Later

Not scheduled; see [Future work](explanation/future-work.md) for each.

- [ ] Faster search: stronger pruning, e.g. a rest look-ahead or a tighter workload bound (tried 2026-11-13 and not worth
      it: workload caps that account for overlaps; symmetry between identical workers, rare in the benchmark)
- [ ] Faster search by non-heuristic means: parallelization, a compiled core (PyPy adopted for development runs, ADR 0033)
- [ ] Explaining more fully why an input is infeasible
- [ ] Audit: why some samples have no easy fix at all (seed 16 of the example)
- [ ] Tuning: check the defaults on 48-hour schedules, including load within a day, once the search finishes them
- [ ] Scoring: a fairness term for liked pairings, if counting liked-partner complaints apart in the audit turns out
      wrong (see `explanation/future-work.md`)
- [ ] Handling dangling shifts (keep, merge, or set a minimum length)
- [ ] Time and post preferences
- [ ] Forcing a specific worker into a specific shift (low priority)
- [ ] Right-to-left spreadsheets
- [ ] Docs: tutorials, generated API reference, publishing the site
- [ ] An optional graphical interface, for people who don't use the command line
- [ ] Distribution needing no installation, run by clicking one obvious file (command line or GUI), for Windows and Linux, possibly macOS
