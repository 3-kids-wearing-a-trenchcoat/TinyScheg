# Roadmap

The work left to make TinyScheg produce fair schedules, in the order it's planned. Each step links to the design it
implements. Component status is in the [status table](index.md#implementation-status); ideas that aren't scheduled
yet are described in [Future work](explanation/future-work.md).

When something is deferred, it goes both into [Later](#later) here and into
[Future work](explanation/future-work.md).

Progress: Phases 1–8 complete (Phase 8 on 2026-11-15); the penalty's parts made flat after Phase 7 ([ADR 0032](decisions/0032-flat-penalty-parts.md)); PyPy for development runs ([ADR 0033](decisions/0033-pypy-for-development-runs.md)); never back to back ([ADR 0034](decisions/0034-never-back-to-back.md)); Phase 9, parallel search, complete
(2026-11-15); Phase 10, the defaults on long schedules, complete (2026-11-16); Phase 11, faster search through the
bounds, in progress (steps 1–5 done, 2026-11-17).

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
  example took about 10 seconds after the tuning speed-ups; at the weights of ADR 0039, with the bound of ADR 0040,
  it took about half a minute in one process, 9 seconds on PyPy; with the cheaper bound checked first, about 20
  seconds, 5½ on PyPy, and about 2 seconds with the parallel search of Phase 9 (2026-11-15). The 48-hour example
  takes about 12 minutes on PyPy in parallel, against an estimated hour in one process.)
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
      ([ADR 0028](decisions/0028-rest-factor-default-2-5.md)). The 48-hour tier was out of the search's reach then;
      it was checked in Phase 10

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

- [x] **Search progress and Ctrl+C** ([ADR 0035](decisions/0035-search-progress-and-keeping-the-best-on-interrupt.md))
    - [x] The share of the search space finished, tracked by the search, which only observes
    - [x] Command line: a two-line block redrawn in place on a terminal (the best schedule so far, and the progress
      with a rough time left); plain lines otherwise
    - [x] Ctrl+C writes the best schedule found so far, marked as not proven the best
- [x] **Rest targets derived from the input** ([ADR 0036](decisions/0036-rest-targets-from-the-input-convex-per-worker.md)):
  the rest factor is the schedule's own ratio of free time to work instead of a value chosen by hand, the target for
  the rest between two shifts comes from both their lengths, and each worker's shortfall is squared; `rest_factor`
  removed; the provable properties of the rest part as tests
- [x] **Each worker's worst rest deficit from scratch over the history**
  ([ADR 0037](decisions/0037-worst-rest-deficit-from-scratch-over-the-history.md)): a history slot counts for
  everyone who was available for it and had its role that day, not only for whoever worked it
- [x] **Rests measured in available time** ([ADR 0038](decisions/0038-rests-count-only-available-time.md)):
  unavailable time inside a rest counts as neither work nor rest; the hard minimum rest stays on the clock
- [x] **The weights re-checked** ([ADR 0039](decisions/0039-default-weights-from-the-users-trade-offs.md)): set from
  the user's trade-offs, likes : workload : rest = 0.45 : 1 : 0.25 and neutral partner 0.44, judged by the
  user's rules first, measures that don't come from the audit second and the audit last; the trade-offs tested at
  the defaults
- [x] **A workload bound in whole slots** ([ADR 0040](decisions/0040-workload-bound-in-whole-slots.md)): the heavier
  workload weight made the search 3–7 times slower, and `confirm_01` about 2 hours, because the bound spread the
  remaining work as if it could be split finely; the bound now also hands it out in whole slots, with exactly the
  same results on every benchmark input

## Phase 9: Parallel search

Using every processor for one search, without changing its result
([ADR 0041](decisions/0041-parallel-search-with-the-sequential-result.md)).

- [x] Measure the ceiling before building anything: the work splits evenly into a few hundred subtrees
- [x] A prototype, checked for identical results under random delays and timed one input at a time: 7.6 times faster
  with 8 processes, with as many nodes in all
- [x] The parallel search (`csp/parallel.py`): subtrees in the sequential order, a shared best whose subtree number
  decides ties, progress, new bests and Ctrl+C through shared memory; the command line's `--jobs`, by default one
  process per processor; the sequential search unchanged with one process
- [x] Tests, and every benchmark input, alone and as day 2, with the recorded schedules

## Phase 10: The defaults on long schedules

Checking the defaults on 48-hour schedules, the length the user's schedules usually run to, and the loose ends the
check turned up (planned 2026-11-16). Runs with no time limit come last.

- [x] Finish the runs that were cut short and are now fast: the defaults audited on the confirm tier (`confirm_01`
      timed out in the check of [ADR 0039](decisions/0039-default-weights-from-the-users-trade-offs.md)), and the
      workload weight 1.25 on `sweep_02` (done 2026-11-16: `confirm_01` gives the recorded schedule, with 4
      complaints, 2 of them with a small easy fix; the weight 1.25 gives the defaults' schedules on every tuning input)
- [x] Diagnose the 48-hour check's findings, by how the fixing change moves each part of the penalty: load within a
      day on `multiday_05` (one swap removes 5 complaints), 12 short-straw complaints with an easy fix on
      `multiday_04`, and a 4-against-6 shift gap over both periods on `multiday_05` (done 2026-11-16: the scoring
      can't see load within a day, as the swap leaves workload and rest unchanged; the audit counts short rests but not
      how short, so its fixes there make a rest of 12 hours one of 7; the gap is forced by a scarce role)
- [x] Decide on the defaults: they hold, a small tuning round on the 48-hour inputs, or a design question for the
      user (decided 2026-11-16: they hold, for now; load within a day is left to the whole schedule's totals, since
      the uneven day on `multiday_05` was only when a long rest fell, with even totals; the audit no longer counts a
      change that makes a short rest shorter as harmless, which removed `multiday_04`'s fixes and changed no
      conclusion of the weight re-check)
- [x] The next period is the same hours a whole number of days later (the user, 2026-11-16): fix the tuning's
      second period to match, and re-run the second periods it changes (done 2026-11-16: at the defaults, all 8
      moved second periods have a legal schedule, against 3 of 8 before; of every benchmark input, only `sweep_08`
      still leaves the next period none)
- [x] Warn when a schedule leaves the next period with no legal schedule, after a cheap check with a node limit
      ([ADR 0042](decisions/0042-warn-when-the-next-period-cant-be-filled.md); done 2026-11-16: `sweep_08` and the
      example warn)
- [x] The 48-hour tier reproducible by the generator: 5 inputs, a 2-hour limit (seed 3008 took 54 minutes)
- [x] Docs: the 48-hour results on the tuning page and in future work
- [x] Search time on 48-hour schedules: about half the generated inputs take over half an hour; what that means for
      real use, and what could help (decided 2026-11-16: accepted for now; on the tier's inputs each search found
      its best schedule within its first 41%, and one within 0.1% of its penalty within 40 s, so Ctrl+C gives a
      near-final schedule early, and a second period, with history, takes at most 8½ minutes; but seed 3009, in the
      next step, came within 0.1% only after 31 minutes, and found its best after 3¾ hours; faster first periods
      taken up in [Phase 11](#phase-11-faster-search-through-the-bounds))
- [x] Runs with no time limit, unattended: how long the 48-hour seeds 3009–3011 take to search to the end (done
      2026-11-16 for seed 3009 only: 5 hours 57 minutes on the laptop, 12.7 billion nodes, its best schedule found
      after 3 hours 46; seeds 3010 and 3011 dropped by the user, for Phase 11 instead)

## Phase 11: Faster search through the bounds

Making the proof that nothing beats the best schedule cheaper, for 48-hour first periods above all (up to 6 hours on
the laptop, Phase 10), without changing any result: each candidate is a valid lower bound, which changes only how much
is pruned, never the schedule (planned 2026-11-16; see
[Search time on 48-hour first periods](explanation/future-work.md#search-time-on-48-hour-first-periods)).

- [x] **1. Measure first,** outside the program: at sampled nodes of a few inputs, how far the current bounds are below
      the best completion, how often each candidate below would prune where they don't, and at what depth; and how
      many values of the multiplier the whole-slot bound tries (done 2026-11-16, on 17 inputs, every candidate giving
      the same schedules; see [Future work](explanation/future-work.md#search-performance)): the exact multiplier
      and the rest look-ahead are worth building, a role-aware bound in a cheap form is worth designing; starting the
      multiplier from the parent's (more nodes, not fewer) and a strong bound near the top of the tree only (the
      pruning that matters is deep) are dropped

Every step below keeps exactly the same schedules: each new bound is a valid lower bound, never above any
completion. Each is checked as the earlier speed-ups were: every benchmark input alone and as a second period, on
CPython and on PyPy, against the recorded schedules, and the 48-hour inputs. It's judged by **time**, not nodes: a
tighter bound has to pay for its own cost, measured in one process and in parallel. Each code change needs the
user's approval first.

- [x] **2. The exact multiplier**, with [ADR 0044](decisions/0044-best-whole-slot-multiplier-by-tangents.md) amending
      [ADR 0040](decisions/0040-workload-bound-in-whole-slots.md): the whole-slot bound's best multiplier computed
      instead of searched for with about five tries (`MU_STEPS`) (done 2026-11-17)
    - [x] Two exact methods compared outside the program first: each worker's lower convex envelope merged by slope
      (the plan; with one load left, a priority queue), and tangents on the concave bound, which reuse its evaluators
      and stop when the value reaches the tangents' crossing. The same values; the envelope 2.5 times slower on PyPy
      (worst on 48-hour inputs), faster only on CPython's small inputs. The user chose tangents
    - [x] Tests: equal to a long multiplier search on random states (exact and interval sets, powers 2 and 3), a
      function known by hand; never above the best completion (brute force, as before)
    - [x] Check: the same schedules on every benchmark input, alone and as day 2, on CPython and PyPy with 12
      processes; in one process against `dev`'s code, 12% less time on PyPy (16 inputs to the end), 15% less on
      CPython (6 small inputs), 1.3–1.7 times the progress on 48-hour inputs; up to 12% slower where it prunes no
      more (`sweep_11`)
- [x] **3. The rest look-ahead**, with [ADR 0045](decisions/0045-rest-lookahead.md) (done 2026-11-17): for each
      unfilled slot, the smallest increase in the rest penalty among the workers still in its domain, against their
      current shifts; slots that conflict pairwise go to different workers, so the heaviest such group is added to the
      bound, found from the neighbour lists (conflicts follow time like intervals). Computed afresh where the rest of
      the bound doesn't prune, and from scratch near a tie, so the decisions are the same with or without incremental
      scores
    - [x] Lab first: asked before the whole-slot part, it cost more than it saved; a quicker zero test saved a quarter
      of its cost at most. The user chose the simple version, asked last
    - [x] Tests: never above what a completion adds (brute force on partial schedules), above 0 on some; the same
      search result with and without it
    - [x] Check: the same schedules everywhere (alone and day 2, CPython and PyPy, 12 processes); one process against
      `dev`: 4–7% less time on PyPy (`sweep_12` 35% less), seed 3009 2.3 and `multiday_04` 1.7–1.85 times the
      progress; up to 12% slower where no rest cost is certain (`sweep_11`, `multiday_05`); as day 2 with 12
      processes, 17–20% less
- [x] **4. A role-aware workload bound**, with
      [ADR 0046](decisions/0046-whole-slot-sets-from-each-workers-own-domain.md) (done 2026-11-17): the whole-slot
      bound's sets from each worker's own domain, counted per load, kept up to date incrementally and cached
    - [x] Lab first: groups of slots with a price each (water-filling and whole slots) never bound; a price per slot
      (the ceiling) cost 80–100 µs per node; the per-worker sets beat it, and pay their way only replacing the global
      sets with incremental counts. The user chose to adopt them as they are
    - [x] Tests: never above brute force, equal to a long multiplier search, a case by hand where only these reach the
      best completion; incremental equal to from scratch
    - [x] Check: the same schedules everywhere (alone and day 2, CPython and PyPy, 12 processes); one process against
      `dev`: 6–10% less time on PyPy, 13% on CPython; `multiday_05` 60–71 and seed 3009 3.5–3.9 times the progress,
      `multiday_05` to the end in 689 s and 230 s for the two periods (3107 s and 505 s on 2026-11-16); up to about a
      third slower where domains aren't narrowed (`sweep_06`; `multiday_04` 0.9 times). An on/off setting deferred
- [x] **5. Smaller, if still worth it after 2–4:** the per-worker sets' bookkeeping made cheaper (ADR 0046); fixed data
      not rebuilt at each node; children whose own penalty already reaches the pocket's skipped without being set up
      (0–16% of nodes); the whole-slot bound only where the cheap bound is near the pocket's (2026-11-17, lab first,
      one process on PyPy; see [Future work](explanation/future-work.md#search-performance))
    - [x] Kept: each worker's sets cached in a plain dict keyed by their counts, instead of `lru_cache` (run as Python
      code on PyPy) keyed by pairs built at every bound; the same search node for node, 11–32% less time with the
      role-aware bound on. The user approved it, on branch `phase11-sets-cache`
    - [x] Not taken: skipping children that can't beat the pocket (0.3–11% of nodes skipped, 14–36% slower on four
      inputs); the whole-slot bound only near the pocket (no gap that saves calls without losing prunes); each
      worker's extra loads as a sorted list with a binary search and the fixed parts computed once (28% less on
      CPython, even on PyPy: faster on `multiday_05`, slower on small inputs; a lead, in a form using the list only
      where it's short)
    - [x] Check: the same schedules everywhere (alone and day 2, CPython and PyPy, 12 processes); one process
      against `dev` at the default (`auto`), PyPy: 11–20% less time where `auto` turns the bound on (`sweep_08` 0.80,
      `multiday_05` and `confirm_01` 0.85, `multiday_04` 0.87, `multiday_04`'s second period 0.89), seed 3009 0.96;
      where it's off, the code is unchanged (`sweep_11` 1.24 in the batch, 1.07 timed again alone, the same nodes);
      CPython 0.96–1.00 on 6 small inputs
    - [x] `auto`'s rule (ADR 0047) measured again with the cheaper bound, on the comparisons it was fitted and checked
      on: still the best of the policies (51 comparisons: always off 1240 s, always on 1198 s, `auto` 1166 s, the best
      every time 1159 s), on and off now within about 5% where on prunes no more. The user kept the rule as it is
- [ ] **6. Docs and new timings:** the ADRs, the scoring and search explanations, the API reference, future work;
      the 48-hour times measured again on the laptop (the tier's 5 inputs and seed 3009, in parallel), and the
      deferred item on 48-hour first periods reconsidered with them
    - [x] After steps 2–4 (2026-11-17, 12 processes, PyPy, `auto`; see
      [Future work](explanation/future-work.md#after-phase-11s-steps-24-2026-11-17)): the same schedules; first
      periods 2 h 16 min in all against 7 h 22 (3.3 times), seed 3009 1 h 40 min against 5 h 57, `multiday_05` 4.2
      times, `multiday_02` even; `multiday_04`'s second period 15% slower, `auto` choosing on where off is faster.
      The deferred item stays open: seed 3009 is still well over half an hour
    - [ ] After step 5, if it changes the search's speed

## Later

Not scheduled; see [Future work](explanation/future-work.md) for each.

- [ ] Faster search: stronger pruning, e.g. a rest look-ahead, or whole-slot sets per worker's own domains (a
      workload bound in whole slots was done in Phase 8, ADR 0040; tried 2026-11-13 and not worth it: workload caps
      that account for overlaps, and symmetry between identical workers, rare in the benchmark; Phase 11 takes up
      the rest look-ahead, the exact multiplier and roles). Left after Phase 11's measurement: workload slack from
      slots too close together for one worker to take both, which no bound tried sees, and loose inputs with no
      scarce roles (`multiday_02`), where nothing tried helped more than 7%
- [x] Faster search by non-heuristic means, as far as it's worth going: PyPy for development runs (ADR 0033),
      parallel search (Phase 9, ADR 0041), and the bound without its whole-slot part checked first (2026-11-15); a
      compiled core and domains as bitsets decided against for now (see future work)
- [ ] Faster search for 48-hour first periods, with no history: up to 6 hours on the laptop, most of it proving
      that nothing beats a schedule found early (deferred in Phase 10; the bounds taken up in Phase 11)
- [ ] The rest look-ahead kept up to date incrementally, or with a quicker test for slots that add nothing, to cut its
      4–12% cost (ADR 0045); and the tangent search's dials tuned (ADR 0044). Only if ever worth it (2026-11-17)
- [x] A setting to turn the whole-slot bound's per-worker sets (ADR 0046) on or off, since they cost up to about a
      third more time where roles and availability don't narrow the domains, and chosen automatically from how
      constrained the input is (asked by the user, done 2026-11-17, ADR 0047: `role_aware_bound`, `auto` by default)
- [ ] A strong bound used only near the top of the tree, where a prune removes the most: a multiplier per slot, each
      worker's best set of slots found on its own, covering roles, overlaps, rest and workload together (too costly
      at every node; suggested 2026-11-16)
- [ ] Parallel search where processes are spawned (Windows, macOS): measure the start-up cost, and reconsider the
      default if need be, before distribution
- [ ] Explaining more fully why an input is infeasible
- [ ] Audit: why some samples have no easy fix at all (e.g. seed 150 of the example)
- [x] Tuning: check the defaults on 48-hour schedules, including load within a day (done in Phase 10: they hold, for
      now)
- [ ] Scoring: a fairness term for liked pairings, if counting liked-partner complaints apart in the audit turns out
      wrong (see `explanation/future-work.md`)
- [ ] Scoring: compensation across parts, each worker's rest shortfall and pairings (and perhaps workload) through one
      convex function, so that a liked shift makes up for a short straw (deferred until the weight re-check, now
      done)
- [ ] Scoring: workload in hours only (shift share 0), once the rest part keeps short shifts apart in tight schedules
      too (deferred 2026-11-14)
- [ ] A schedule that leaves the next period a worse schedule than another first period would (found 2026-11-14;
      one that leaves it no legal schedule is warned about since Phase 10, ADR 0042)
- [x] Tuning: start the second period a whole number of days after the first, so that it covers the same hours of
      the day (done in Phase 10)
- [ ] The example leaves the next period no legal schedule: whether to change it, given it's also the input the
      defaults' trade-offs are checked on (left as it is in Phase 10, to be revisited)
- [ ] Handling dangling shifts (keep, merge, or set a minimum length)
- [ ] Time and post preferences
- [ ] Forcing a specific worker into a specific shift (low priority)
- [ ] Right-to-left spreadsheets
- [ ] Docs: tutorials, generated API reference, publishing the site
- [ ] An optional graphical interface, for people who don't use the command line
- [ ] Distribution needing no installation, run by clicking one obvious file (command line or GUI), for Windows and Linux, possibly macOS
