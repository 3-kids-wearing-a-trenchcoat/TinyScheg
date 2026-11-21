# Roadmap

The work left to make TinyScheg produce fair schedules, in the order it's planned. Each step links to the design it
implements. Component status is in the [status table](index.md#implementation-status); ideas that aren't scheduled
yet are described in [Future work](explanation/future-work.md).

When something is deferred, it goes both into [Later](#later) here and into
[Future work](explanation/future-work.md).

Progress: Phases 1–8 complete (Phase 8 on 2026-11-15); the penalty's parts made flat after Phase 7 ([ADR 0032](decisions/0032-flat-penalty-parts.md)); PyPy for development runs ([ADR 0033](decisions/0033-pypy-for-development-runs.md)); never back to back ([ADR 0034](decisions/0034-never-back-to-back.md)); Phase 9, parallel search, complete
(2026-11-15); Phase 10, the defaults on long schedules, complete (2026-11-16); Phase 11, faster search through the
bounds, complete (2026-11-18); Phase 12, where speed is left on the table, closed by the user (2026-11-19); Phase 13, a reliable audit, started
(2026-11-19; steps 1 to 3, the decisions, the design and the rebuilt audit, done; step 4 under way, its cards read by
hand changing four rules, [ADR 0051](decisions/0051-the-audit-after-reading-cards-by-hand.md)).

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
- [x] **6. Docs and new timings:** the ADRs, the scoring and search explanations, the API reference, future work;
      the 48-hour times measured again on the laptop (the tier's 5 inputs and seed 3009, in parallel), and the
      deferred item on 48-hour first periods reconsidered with them
    - [x] After steps 2–4 (2026-11-17, 12 processes, PyPy, `auto`; see
      [Future work](explanation/future-work.md#after-phase-11s-steps-24-2026-11-17)): the same schedules; first
      periods 2 h 16 min in all against 7 h 22 (3.3 times), seed 3009 1 h 40 min against 5 h 57, `multiday_05` 4.2
      times, `multiday_02` even; `multiday_04`'s second period 15% slower, `auto` choosing on where off is faster.
      The deferred item stays open: seed 3009 is still well over half an hour
    - [x] After step 5 (2026-11-18, the same way; see
      [Future work](explanation/future-work.md#after-phase-11s-step-5-2026-11-18)): the same schedules; first periods
      2 h in all (3.7 times the speed of 2026-11-16), seed 3009 1 h 28 min, `multiday_05` 619 s (5.0 times); 7–15% less
      than after steps 2–4 wherever the role-aware bound is on
    - [x] The deferred item on 48-hour first periods reconsidered with these (2026-11-18): kept deferred, with the
      new numbers and the leads left (the user closed Phase 11). The tier's five now take 2–12 minutes; seed 3009,
      one generated input, is the outlier at 1 h 28 min, within 0.1% of its best after 8

## Phase 12: Where speed is left on the table

Before the defaults are tuned further, which will mean generating many schedules, the speed-ups not yet explored are
measured, to see which are worth building (planned 2026-11-18). Phase 11 worked on the bounds and the cost per node;
this phase also looks at when the best schedule is found, the shape of the search tree, dominance between partial
schedules, and how many searches can be run at once. Every measurement is made outside the program (a lab copy under
`tools/benchmarks/results/`), on the example and the 15 benchmark inputs searched to the end, and on `multiday_04`,
`multiday_05` and seed 3009 (with a node limit where searching to the end takes too long). After each, its results
and conclusions are reported to the user.

- [x] **1. Measure,** one at a time, in this order (the first four decide which of the others are worth making):
    - [x] The best penalty known from the start: the pocket's threshold set to the best penalty plus the near-tie
      margin, which keeps the same schedule; how much time goes to searching before the best schedule is found (done
      2026-11-18, the same schedule in all 41 searches): the 16 small inputs, one process, 0.72 of the nodes and 0.74
      of the time (first periods 0.33–1.00, second periods 0.13–0.95); the 48-hour first periods, 12 processes,
      0.93–0.99 of the time, seed 3009 0.90 (1 h 19 against 1 h 28), though its best comes at 54 minutes; their second
      periods 0.73–0.87. On the slow searches nearly all the time is the proof, which no better first schedule
      shortens; a better first schedule would help short searches, as tuning runs them, most
    - [x] A fresh profile on PyPy: where each node's time goes after Phase 11, and code that leaves the JIT's
      compiled code (done 2026-11-18): 10–12 µs per node on every input; the JIT healthy (under 1 s of tracing in
      30 s, few aborts); cProfile triples the time and inflates small functions, so each part was also timed by running
      it twice: water-filling about 17–42% of the time, the whole-slot bound 20–35% where it's on, the rest changes
      13–20%, the rest look-ahead up to 20%, the rest small (rough, overlapping figures). The rest's hours computed
      from whole microseconds worked out once, instead of subtracting datetimes at every call (PyPy runs `datetime`
      as Python code): exactly the same values, 8–17% less time; a candidate to build, with a cheaper water-filling
    - [x] How close the kept nodes come to being pruned: the gap between each kept node's bound and the threshold, by
      depth; whether a slightly tighter bound would prune much (done 2026-11-18, the proof's nodes, with the threshold
      at the best penalty): the root's bound is 1–8% below the best penalty; a bound higher by 1% of that gap at every
      node would leave 0.91 of the nodes, by 3% 0.77, by 10% 0.44, by 30% 0.09 (the inputs searched to the end), so
      the nodes aren't piled up just short of being pruned, except on `multiday_05` (3% leaves 0.17), and least on the
      loose `multiday_02` (10% leaves 0.78). Most kept nodes are in the middle and lower part of the tree, where they
      have only 5–15% of the root's gap left
    - [x] The gap left after Phase 11: at sampled deep nodes, the bound against the best completion, split into
      workload (whole slots, roles, slots too close together for one worker), rest and likes (done 2026-11-18, about
      110 kept nodes with at most 14 slots left on each of 34 searches): on average rest 43% of the gap, workload
      30%, likes 27%; 63% is each part's own bound's slack (rest 28%, workload 24%, likes 11%) and 37% the best
      completion's trade-offs between the parts, which no bound on one part sees. Of the workload's own slack,
      slots too close together for one worker are only 4% of the gap; the rest (19%) is how slots and workers are
      matched given roles and whole slots, which the one multiplier doesn't see: on `multiday_04` and `multiday_05`
      that's 80–92% of the gap. The rest's own slack is largest on second periods
    - [x] ~~Workload caps that count slots too close together for one worker~~, replaced by the user (2026-11-18)
      after measurement 4 found those slots only 4% of the gap: a workload bound that matches the unfilled slots to
      the workers in their domains, conflicts relaxed, exactly (a greedy over the counts, exact as they form a
      polymatroid; the few slots of another load than the commonest enumerated). Done 2026-11-18, outside the
      program, asked where the program's bounds don't prune: the same schedule on every input; 0.55 of the nodes on
      the 29 small searches run to the end (`confirm_03` 0.015, `sweep_07` 0.16, `sweep_09`'s second period 0.23,
      the example 0.45, `confirm_01` 0.52; no change on `sweep_02`, `sweep_04`, `sweep_11`, where too many slots
      have another load to enumerate); `multiday_05` searched to the end in 104,698 nodes (about 248 million in the
      program's proof), seed 3009 1.4 times the progress in 5 million nodes. Versions that round the other loads
      instead were valid but pruned almost nothing. As written it costs up to about 3 ms a call, most of the time
    - [x] Exactly tied schedules: how often two schedules tie at the best penalty, which decides whether another
      order of the search would change any result (done 2026-11-18): more than one on 24 of 37 searches, often
      hundreds or thousands (`sweep_06` 4,416, `confirm_01` 1,728; `multiday_05` 640 in its first 100 million
      nodes), fewer on second periods; none within 1e-6 that aren't exact; almost none from identical workers. Another
      order would usually keep another schedule, so it would need a tie rule of its own; and the tree is full of
      equivalent subtrees, which makes dominance worth measuring
    - [x] Other orders of the slots (largest rise of the bound, largest regret, by time), with the threshold at the
      best penalty: the effect of the tree's shape alone (done 2026-11-18; the bound's rise taken as the cheapest
      worker's cost, and regret's also as mrv's tie-break): no order beats the program's overall (31 searches to
      the end: the cheapest worker's cost 1.49 of its nodes, regret 2.08, mrv with regret 1.05, by time 20, five
      of its searches stopped at 50 million nodes), but every order is far better somewhere: mrv with regret on 17
      of 31, mostly second periods (`sweep_04`'s 0.14, `sweep_03`'s 0.18); by time `multiday_02` 6.9 times the
      progress, the cheapest worker's cost `multiday_05` 15.5 times, and each far worse elsewhere. Another order
      usually keeps another tied schedule (6–12 of 31)
    - [x] Each worker's number of shifts decided first: how many vectors of counts have a workload bound below the
      best penalty (done 2026-11-18, at the root, conflicts relaxed, an upper estimate where loads differ): 120–360 on
      a few one- or two-load inputs (`sweep_04`, `sweep_01`, `multiday_02`), thousands to a million on most small
      inputs, over 2 million (where counting stopped) on 25 of 40, every 48-hour input but `multiday_02` among them:
      deciding the counts first would mean far too many searches; not worth building
    - [x] Dominance: how often swapping filled slots between two workers lowers the penalty without changing what's
      left to fill (done 2026-11-18, with a safe test: the same loads, their shifts full, no unfilled slot near
      either or among their neighbours, nobody's deficit higher): a strictly better swap at under 0.5% of the kept
      nodes, an equal one (a tie) at up to 26%, but only deep in the tree, where little is left below; pruning both
      (the equal ones by a fixed rule for which twin to keep) left 0.998 of the nodes. Not worth building in this
      form; the ties of measurement 6 would need a test that sees symmetry higher up
    - [x] Many searches at once: a batch run one after another with 12 processes each against side by side with one
      process each, and the cost of starting up and warming up on small inputs (done 2026-11-18, 30 searches, each
      a fresh process, two rounds): PyPy one after another with 12 processes 99–107 s, side by side with one process
      131–141 s, 6 at a time with 2 processes 95–96 s; CPython 193 s and 536 s. Side by side, each search ran about 1.35
      times as long as alone (heat), and the batch waited on its longest search; their time added up to 43 s per
      process, against about 96 s of searching one after another, so a large batch would run about twice as fast
      side by side. Starting up and reading the input: 0.3–0.6 s on PyPy, 0.1–0.16 s on CPython, which is faster on
      searches of under about 2 s
    - [x] Parallel search: the speed-up with 1–12 processes, and how long each process waits for work (done
      2026-11-18, PyPy, on the laptop): with 12 processes 2.8–4.9 times one process' speed (`sweep_02` 4.86,
      `confirm_01` 4.41, `sweep_11`'s second period 3.48, slower than with 8), with 2 processes 1.8–2.0; the processes
      are busy 94–100% of the time, idle at the end under 2%, and the nodes about the same: what's lost is each
      process's own speed as more run (4 full and 8 compact cores, and heat), not the search's division of work
- [x] **2. Choose** what to build, from the measurements, with the user (2026-11-18): cheaper nodes first (the lower
      hanging fruit), then the exact matching bound; the rest deferred (see [Later](#later)). Each step below keeps
      every node and schedule exactly the same (a valid bound changes only the nodes), checked as in Phase 11, and is
      judged by time; each is on its own branch from `dev`, with the user's approval, and needs no ADR where it
      changes no behaviour (as with Phase 11 step 5)
- [x] **3. The rest's hours without date and time arithmetic:** each slot's start and end in whole microseconds from
      the first slot's, worked out once in the scoring constants, instead of subtracting datetimes at every rest
      (PyPy runs `datetime` as Python code); the same values, exactly (done 2026-11-18, the user approving it, on
      branch `phase12-rest-hours`). Check: every rest's deficit equal to the old arithmetic to the last bit (tests);
      the same nodes, schedules and penalties as `dev` on every input alone and as day 2, one process on PyPy and
      CPython and 12 processes on both. About 4–5% less time, not the 8–17% measurement 2 suggested (its baseline was
      slowed by heat): seed 3009 0.95, `confirm_01` 0.96, `multiday_04` 0.96, `multiday_05` 0.99, `sweep_11` within
      noise (2 million nodes, three alternating rounds); the benchmark set 0.964 on PyPy, 0.974 on CPython
- [x] ~~**4. The exact matching workload bound**~~ (measurement 5), made cheap enough to pay (moved before the
      water-filling by the user, 2026-11-18): lab done, stopped by the user (2026-11-19), not built
    - [x] Lab, each version checked to decide exactly as the prototype does (four versions, the last asking only
      whether it prunes, skipping the matching where each worker's best count on their own can already be matched,
      and repairing the counts by exchanges otherwise): 40 µs to 1.6 ms a call; the same schedules everywhere.
      Against the program: `multiday_05` searched to the end in 9 s on one process (about 10 minutes on 12),
      `multiday_04` about 90 times the progress, `confirm_03` 0.30 of the time; but the small inputs 1.45 times
      slower in total (27 of 30 slower), seed 3009 0.58 of the progress, `multiday_02` 0.41. No rule found that tells
      the inputs it helps from those it slows (the role-aware bound's `auto` doesn't), and a setting a user can't know
      when to turn on wasn't worth its upkeep. Kept for [Later](#later) as an opt-in setting
    - [x] ~~An ADR, the code (on its own branch), tests, the check, the 48-hour times~~ (stopped with the step)
- [x] ~~**5. A cheaper water-filling**~~ (lab first: fewer allocations with the same arithmetic; the change points
      kept sorted from node to node; each worker's term reused): stopped by the user before its lab (2026-11-19),
      the gain likely small (step 3's measured 4–5% against measurement 2's 8–17%), as speed work had reached
      diminishing returns
- [x] **6. Docs:** the API reference (done with step 3), future work (the matching bound's lab, 2026-11-19); the
      scoring and search explanations unchanged (step 3 changes no behaviour), and the 48-hour times not measured
      again for step 3's 4–5%

## Phase 13: A reliable audit

The [schedule audit](explanation/schedule-audit.md) is what the scoring is tuned against, so before the scoring
changes again, the audit is made reliable (planned with the user, 2026-11-19). Today it puts values on what it finds:
short rests and disliked partners are added together one for one, a short rest is a fixed margin below the typical
rest, severities are summed across kinds and across pairs of workers (so the totals grow with the number of peers),
load is also compared in any 24 hours, and fixes are found greedily, with at most three changes. The aim is an audit
that only **observes**, with nothing given a number or value to tune: for each worker, a list of grievances, each one
event the worker can point to (such as an extra shift, a short rest, or a shift with someone they dislike), with its
facts and an easy fix where one is found; no scores, no summary verdict, no "unavoidable" label, and no kind set
apart. What matters more (one kind against another, evenness against the total, which grievances could have been
avoided) is decided where the results are read, in tuning, outside the audit, so that a surprising result can be
traced either to the audit describing the schedule wrongly or to how it was read. Where a question has no clear
answer, the audit asserts only what holds under every reasonable answer.

- [x] **1. Decide** what the audit is, a group of decisions at a time, each discussed with the user (the options,
      examples, a recommendation). The decisions depend on each other, so they're taken in this order, going back
      where a later one changes an earlier one; decisions found along the way are added in their place:
    - [x] **Foundations** (decided 2026-11-19): a grievance is an **event** the worker can point to (an extra shift,
      a short rest, a shift with someone they dislike), not a comparison that counts only past a tolerance, which
      would build in "someone had to"; whatever line an event needs is drawn from the schedule itself, so that the
      same work and rest for everyone is fair however long they are. So the audit measures fairness, not how good the
      schedule is otherwise, and tuning reads it together with the measures that don't come from the audit (everyone
      resting less but equally is no grievance; among the tuning results so far, something like it appeared once, on
      one input, by an hour). Where an event is measured against peers (load), it's against the **best-off peer**,
      not one per peer, which grew with the number of peers. The horizon stays the whole schedule, with the history
      the input carries, fixes changing only the new period. The audit models workers **sensitive to being treated
      unfairly**: each points to every way they were worse off than a peer, never to a way they were better off, and
      makes the strongest case they can (hence the best-off peer; and they never set a boon against a straw).
      Taken up in later groups: a short rest needs a line drawn from the schedule (rest); and for load, no change is
      harmless any more (moving a shift turns one worker's extra shift into another's), so changes are reported by
      what they remove and what they create (easy fixes)
    - [x] **Who is compared with whom** (decided 2026-11-19): load is judged **in proportion to availability**, the
      project's own workload policy ([ADR 0013](decisions/0013-availability-weighted-workload.md)), in shifts and in
      hours (how an hours excess becomes events is the load group's): each worker is compared only with peers
      available at least as long, whose load is scaled down to the worker's availability, never up (scaling up a
      barely available peer's load would turn a fraction of a shift into whole grievances), and only whole extra
      shifts count. Availability counts only the hours when at least one post is staffed (being unavailable when there
      was nothing to do costs nothing, so it doesn't lower what a worker owes), not weighted by how much work there was
      (a different policy, which ADR 0013 doesn't adopt; to revisit if it turns out to matter). Roles stay ignored when
      finding grievances: availability defines what a worker owes, roles only limit what they can do ("a role isn't a
      punishment"), and the fix search shows when nothing could be done. Still missed: a worker available longer,
      against one available much less who did proportionally less
    - [x] **Load** (decided 2026-11-19): shifts and hours with no exchange rate, each in proportion to availability: a
      worker did more than a peer only if more by one measure and no less by the other. Against each peer (scaled down
      to the worker's availability), each whole extra shift is an event, with no tolerance (in a 2-2-3 split, the
      worker with 3 has one); an excess in hours is counted in the worker's own shifts, shortest first, so that each
      event is a shift they can point to (dividing it by their shortest shift, as today, could count more events than
      they have shifts); where both measures show more, the larger count; the best-off peer is the one giving the most
      events. The 24-hour window is dropped, after a lab check (2026-11-19: 62 stored tuning schedules longer than 24
      hours, 1,050 per-day complaints, counted per pair): 42% were by workers who also did more over the whole
      schedule, 8% had a short rest in that day; 31% came from doing more of one measure and less of the other over
      the whole schedule (within a day the two line up: a back door to an exchange rate), and 19% were where the work
      fell in time, with as much or less overall (as on `multiday_05`, judged not unfair). What's left, concentration
      in time that no short rest shows, goes to the rest group (a rest judged with the shifts around it)
    - [x] **Rest** (decided 2026-11-19): a rest is only the **available part** of the time between two shifts, as in
      the scoring ([ADR 0038](decisions/0038-rests-count-only-available-time.md)): unavailability is neither work nor
      rest (counted as rest, it would make shifts right around an absence free), and the time between periods counts
      as unavailable for everyone; the legal minimum rest stays on the clock, a rule of what's legal, not something
      the audit judges. A rest is judged **with the shifts around it**, as rest per hour of the two shifts
      (the rest policy of [ADR 0036](decisions/0036-rest-targets-from-the-input-convex-per-worker.md), not a value
      to tune; with shifts of equal length, just the rest): 6 hours between a 12-hour and a 2-hour shift is shorter
      than 6 hours between two 2-hour shifts. Rests are compared **against the best-off peer, rest by rest**: each
      worker's rests sorted shortest first and compared with the peer's in the same places, up to the smaller number
      of rests, each place where the worker's is shorter an event, with how much shorter as a fact on it; no median,
      line or margin, so the same rests for everyone give no event however long they are (pairing in any other order
      would give events even then). Every worker is a peer, with no condition on shifts or availability (rests aren't
      scaled; they're already measured in available time and per hour of work). Rejected: comparing rests only with
      peers who did at least as many shifts, to keep an extra shift from also showing as shorter rests; it would leave
      the worker with the most shifts unmeasured (and one rightly doing more, for being available longer, with no
      grievance of either kind), would turn a badly rested worker's rest events into one load event when given another
      shift, and is a claim about cause; the two are separate events, which can happen without each other (3 shifts
      spread out can rest longer than 2 close together). Also rejected: a short rest as a margin below the typical
      rest (a cliff, a unit from the schedule with rough edges, against a norm rather than a peer); judging rests
      against the worker's own load (a worker resting 6 hours would have a grievance against one resting 4)
    - [x] **Partners** (decided 2026-11-19; the like grievance is the least settled decision so far, below): partners
      are the workers in the other slots of the same shift, as in the scoring. Here workers can be "more greedy than
      fair": a disliked partner is a grievance whatever anyone else got, since the aim is none. Each **disliked
      person in a shift** is an event in itself, with no peer (the line is the worker's own list, not the audit's;
      against the best-off peer it would be the same whenever anyone was spared, and otherwise would excuse a floor
      everyone shares); not per person (5 shifts with X would look like 1) or per shift (X and Y in one shift are two
      events, each with its own fix); the size of the crew doesn't dilute it (the scoring's average over the other
      slots is the model's pricing); each side's own list counts. A **missing like** is only a grievance against a
      peer, judged by the worker's **own** likes applied to the peer's shifts ("your shifts would have put me with
      someone I like more often than mine did", the envy-free test), not by each worker's satisfaction with their own
      list (which compares the luck of two lists: a worker who likes everyone would make everyone else aggrieved);
      counted per liked person per shift, the partners in the peer's shift being its other workers apart from both;
      each event one of the peer's shifts the worker can point to. Every worker can be the peer, and a worker who
      likes nobody has no like grievance; the peer's count is scaled to the worker's number of shifts, down only, and
      only whole pairings count (comparing a peer with fewer shifts as they are never invents a grievance for a
      boon, so unlike load they stay peers, and the worker with the most shifts is measured); the best-off peer is the
      one giving the most events. Levelling down remains (taking a friend from the peer removes the grievance), as
      with rest. The liked pairings each worker got (the greedy side, a boon) are a **fact** on the card, not a
      grievance, and tuning reads them as a total and worker by worker.
      **Less settled:** the user wasn't entirely convinced likes should be compared against peers. The peer-free
      versions each fail: every shift without anyone they like mostly measures the input (the worker with the
      rarest friend is always most aggrieved, and only fewer shifts helps); a liked person on duty at the same time
      at another post never fires with one post and rewards keeping friends apart in time; "never once with X" is
      silenced by one pairing; a pairing a harmless change could add makes the grievance depend on the fix search,
      ruled out at the start. The alternative kept for a revisit is **no like grievance at all**, only the boon count:
      no easy fixes sought for likes, and the reading left to judge who got the friends. The worry behind the doubt,
      liked pairings used as an excuse to load a worker, is answered outside the audit, which never nets: in the
      reading (step 2's tuning page), kinds are never added together, and the rules of
      [ADR 0039](decisions/0039-default-weights-from-the-users-trade-offs.md) apply, likes weighed last, a like
      standing against at most one rest event of the same worker and never against load. Taken up in the output
      group: each rest event showing the shifts around it and who was in them, so that a short rest into a shift
      with a friend can be seen
    - [x] **Easy fixes** (decided 2026-11-19, after a lab check): a fix is a **nearby schedule**, the audited one
      with a few changes (moves, a slot given to another worker, and swaps, two workers exchanging slots in different
      shifts), in the new period only (a grievance about the history with a fix is one the new period could have made
      up for), and legal; the changes only describe how it differs, so their order doesn't matter (the search reaches
      it one legal change at a time, in every order, and tests check on small inputs that this misses nothing), and
      their number, the fix's size, is a fact on it. Only the nearby schedule is judged: audited afresh by the same
      rules (with its own best-off peers; no line from the audited schedule is held steady) and compared with the
      audited one worker by worker and kind by kind, never across kinds. The grievance is gone (the worker has fewer
      events of that kind, with that person for partners); the worker is **better off** in that kind's own terms,
      worse in none of its facts and better in at least one (load: no more shifts and no more hours, fewer of one;
      rest: the new rests compared with the old as with a peer's, none shorter and one longer; dislike: one shift
      fewer with that person; missing like: one more with them), so that making the peer worse off (levelling down)
      is no fix; and the fix is **harmless** if no worker, the aggrieved one included in other kinds, has more events
      of any kind, or a rest event larger when sorted by size. A fix that isn't harmless, a **transfer**, is reported
      too, with exactly what it creates and for whom (with no tolerance, most load fixes are transfers: the extra
      shift in a 2-2-3 can only move); a fix is dropped when another creates a subset of what it creates with no more
      changes (a set comparison, not an exchange rate), so a harmless fix, creating nothing, drops every transfer of
      its size or larger. The search is **complete up to K changes**, the smallest fix first, with only a shortcut
      that can't lose a fix (at least one change touching the grievance's workers), so "no fix" is an exact claim,
      always stated with its K ("no fix of up to 3 changes"): K sets how far the claim reaches, not what a grievance
      is. K is a command-line option of the audit (and of `tools/tune.py`, which passes it on), 3 by default (a named
      constant), not part of the input, which describes the schedule; 0 turns the search off, with no claim about
      fixes either way; each change more multiplies the time by about the number of legal changes (about 30 on
      24-hour schedules, 90 on 48-hour ones). The lab check (2026-11-19, with today's grievance definitions): on 200
      samples of the example, greedy found fixes for 2,522 of 3,131 complaints, and each of the other 609 had a fix
      of 2 or 3 changes judged together; on the 75 stored tuning schedules, 164 more had a fix within 3 changes,
      besides greedy's 358 (most of their complaints are about the history), and 10 needed 4 or more. Requiring each
      step to be harmless and to narrow the grievance blocks preparing steps, and is why seeds 150, 165, 174 and 190
      had no fix at all (on three of them, at most 28 schedules can be reached by harmless steps), though each of
      their complaints has a fix of 2 or 3 changes. Complete up to 3 changes takes up to about 5 minutes on a 48-hour
      schedule and seconds on the example; 4 would take about 100 times more, and 2 misses over a quarter of what 3
      adds to greedy (172 of 609 on the example, 44 of 164 on the tuning schedules). Taken up in the output group:
      how a grievance's transfers are shown; K shown with every claim and recorded in the machine output, and
      comparisons between audits made with different K flagged
    - [x] **Output and checking** (decided 2026-11-19): each worker's **card** shows their facts (shifts and hours,
      availability while a post is staffed, their rests' available part in hours, their partners with counts, and
      their liked pairings, the boon count), then each event: its kind; what it points to (the extra shifts; the
      rest, with the shifts around it and who was in them, so that a short rest into a shift with a friend can be
      seen; the shift and the disliked person; the peer's shift for a missing like); the peer it's measured against,
      with both sides' facts in natural units; its size where it has one (a rest event's in hours: how much longer it
      would have to be to match the peer's, for shifts this long); and its smallest harmless fix with its size, or else
      its transfers, each with exactly what it creates and for whom (all of them, one per line, until reading cards
      shows that's too long), or else "no fix of up to K changes"; an event wholly in the history says so instead,
      since no change can reach it. K is printed at the top. The only **totals** are a closing table of counts, per
      worker (in input order: ranking them would take a rule across kinds) and per kind, each with its events, how
      many have a harmless fix, how many only transfers and how many no fix within K; nothing is added across kinds,
      and there are no severities. The audit returns its events, facts and fixes as data; the command line prints
      the cards, or with `--json` the same as JSON (the standard library's). `tools/tune.py` records for each run,
      per kind, the events, the most aggrieved worker's events (evenness) and the events with a harmless fix (the
      clearest sign the model chose worse than it could have), with the liked-pairings total and K, in its CSV in
      place of the severity columns (each schedule is already stored there, so a full audit can always be rerun;
      the old stages are audited again in step 4). Its report shows each setting's measures side by side, kind by
      kind, with the settings it's dominated by (no better in any measure and worse in one), and **no single
      ranking**: any ranking across kinds is a weighing, done in the reading by the rules step 2 writes on the
      tuning page (never adding kinds, [ADR 0039](decisions/0039-default-weights-from-the-users-trade-offs.md)'s
      rules for likes, most aggrieved first), not in a tool; rows audited with different K are flagged, never
      compared silently. `tools/audit_sample.py` gives the rank correlation of the penalty with each kind's events,
      and as disagreements the samples best by penalty that still have harmless fixes, by kind. The audit stays
      **independent** of `csp/` and `scoring/` (it imports `model/`, `parsing/`, `timing/` and the schedule checker,
      with its own legality check for fixes), so the model never grades itself; `tune.py` and `audit_sample.py` use
      both, comparing them being their job. **Validated** by a hand-made test for each decision, on inputs small
      enough to check by hand (a 2-2-3 split gives one load event with transfers only; equal rests give none;
      levelling down is no fix; the right transfers are dropped; the envy test; peers' load scaled down only); the
      fix search against brute force (every legal schedule within K changes) on small inputs; identical audits on
      PyPy and CPython; the finished tuning stages audited again (step 4), with every grievance that appears or
      disappears explained by a decision, the four seeds found to have fixes, and the time with K = 3 on 48-hour
      schedules measured; and cards read by hand, a sample of them brought to the user covering each kind,
      transfers, "no fix" and events in the history
- [x] **2. Design** (done 2026-11-19): the decisions as two ADRs:
      [ADR 0048](decisions/0048-an-audit-that-only-observes.md) for the audit and
      [ADR 0049](decisions/0049-partners-in-the-audit.md) for partners, apart so that a revisit of the like grievance,
      the least settled decision, supersedes only that one; the [schedule audit](explanation/schedule-audit.md) and
      [tuning](explanation/tuning.md) pages rewritten to match. The reading rules the decisions left open were agreed
      with the user as a first version, to revisit after step 4: within a kind, the events with a harmless fix, then
      the most aggrieved worker's, then all; rest read in hours short too; dominance, with no single ranking; between
      settings neither of which dominates, the user's rules applied by hand, worker by worker; the earlier results
      kept as history, measured with the old audit, and ADR 0039's defaults standing
- [x] **3. The audit rebuilt** (done 2026-11-20; `tools/audit.py`, `tools/audit_sample.py`), in four parts, each with
      its tests: the grievances (2026-11-19), the fix search (2026-11-19, checked against brute force; what a fix
      harms amended by ADR 0050, 2026-11-20), the report (2026-11-20), and the tools reading it (2026-11-20), after
      which the old audit's code was removed; a hand-made test for each decision, and `tools/tune.py` reading its
      output: the measures per kind (for rest also in hours short) with K and each worker's row of the closing table,
      dominance on the inputs both settings finished, results with different K flagged, `tools/tune.py compare` for
      reading two settings worker by worker (both closing tables side by side, then the cells that differ, and
      `--cards` for both full reports of one input), and `reaudit` keeping every earlier file as history
      ([reading the audit](explanation/tuning.md#reading-the-audit)); `tools/audit_sample.py` per kind
- [ ] **4. Validation:** the finished tuning stages audited again (`tools/tune.py reaudit`), the grievances that
      appear and disappear explained, and cards read by hand; the sampled schedules that had no easy fix at all
      (seeds 150, 165, 174 and 190 of the example, taken up from [Later](#later) and answered in step 1) checked to
      have fixes with the new search. Reading cards by hand with the user (2026-11-20) changed four rules
      ([ADR 0051](decisions/0051-the-audit-after-reading-cards-by-hand.md): load in hours alone, a rest judged by the
      shift before it, a missing like as a shift with nobody the worker likes, a dislike cancelling the like it
      meets), after which the stages are audited again. A worker panel, a language model playing each worker
      ([ADR 0052](decisions/0052-a-worker-panel-as-a-check-on-the-audit.md)), checked the audit on all 174 workers of
      the 16 schedules read (2026-11-20), and was then made about 7 times cheaper per worker (2026-11-21). From its
      findings, load is judged against the worker's own share, its events rounded to the nearest shift
      ([ADR 0053](decisions/0053-load-against-the-workers-own-share.md)); whether rest should be judged against a
      typical rest rather than the best-off peer is discussed next, then the stages are audited again and the panel
      checks them
- [ ] **5. Docs:** the how-to, the status table, future work

## Later

Not scheduled; see [Future work](explanation/future-work.md) for each.

- [ ] Faster search: stronger pruning, e.g. a rest look-ahead, or whole-slot sets per worker's own domains (a
      workload bound in whole slots was done in Phase 8, ADR 0040; tried 2026-11-13 and not worth it: workload caps
      that account for overlaps, and symmetry between identical workers, rare in the benchmark; Phase 11 takes up
      the rest look-ahead, the exact multiplier and roles). Left after Phase 11's measurement: workload slack from
      slots too close together for one worker to take both, which no bound tried sees, and loose inputs with no
      scarce roles (`multiday_02`), where nothing tried helped more than 7%. Left after Phase 12's measurements
      (2026-11-18; see [Future work](explanation/future-work.md#phase-12s-measurements-2026-11-18)), besides the
      matching bound taken up in Phase 12: a stronger rest bound (the largest part of the gap left, 43%, and seed
      3009's); a portfolio of slot orders in the parallel search (each order far better on some inputs), which would
      need a tie rule that doesn't depend on the order; bounds across the parts (37% of the gap is what the best
      completion trades between them); dominance higher in the tree than a safe swap test sees. Measured and dropped:
      caps for slots too close together for one worker (4% of the gap), each worker's number of shifts decided first
      (millions of vectors of counts), and any single other order of the slots
- [ ] The exact matching workload bound as an opt-in setting, off by default, for long schedules where roles and
      availability narrow who can fill what (Phase 12 step 4's lab, stopped 2026-11-19: up to about 90 times faster on
      `multiday_04` and `multiday_05`, up to 2.4 times slower elsewhere, with no rule found for when to use it); built
      only if tuning or a real input shows a need. The lab's code is in the local, untracked lab folder
- [ ] Tuning tool: run many searches side by side with one or two processes each, the longest first (measurement
      10: about twice the throughput on a large batch), and start each run's threshold from the previous setting's
      best schedule (measurement 1: the same schedule, 0.74 of the time on the small inputs) (2026-11-18)
- [x] Faster search by non-heuristic means, as far as it's worth going: PyPy for development runs (ADR 0033),
      parallel search (Phase 9, ADR 0041), and the bound without its whole-slot part checked first (2026-11-15); a
      compiled core and domains as bitsets decided against for now (see future work)
- [ ] Faster search for 48-hour first periods, with no history: after Phase 11, 2–12 minutes for the tier's five and
      1 hour 28 for seed 3009 on the laptop (6 hours before), most of it proving that nothing beats a schedule found
      early (deferred in Phase 10, reconsidered and kept deferred at the end of Phase 11, 2026-11-18). Leads: each
      worker's extra loads as a sorted list where it's short (step 5: 0.79 on `multiday_05`, slower on small inputs)
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
- [x] Audit: why some samples have no easy fix at all (e.g. seed 150 of the example); answered in Phase 13, step 1
      (2026-11-19): requiring each step of a fix to be harmless, though each complaint there has a fix of 2 or 3
      changes judged together; step 4 checks the new search finds them
- [x] Tuning: check the defaults on 48-hour schedules, including load within a day (done in Phase 10: they hold, for
      now)
- [ ] Scoring: a fairness term for liked pairings, if the new audit's missing likes (ADR 0049, ADR 0051), read in tuning, show
      their uneven spread matters (it used to say: if counting liked-partner complaints apart turns out wrong; see
      `explanation/future-work.md`)
- [ ] Scoring: compensation across parts, each worker's rest shortfall and pairings (and perhaps workload) through one
      convex function, so that a liked shift makes up for a short straw (deferred until the weight re-check, now
      done)
- [ ] Scoring: workload in hours only (shift share 0), once the rest part keeps short shifts apart in tight schedules
      too (deferred 2026-11-14); since ADR 0051 (2026-11-20) the audit measures load in hours alone, so tuning can
      compare shift shares on the audit's own terms
- [ ] Scoring: the rest target judged by the shift before a rest, as the audit does since ADR 0051 (2026-11-20),
      instead of the mean of the two shifts around it (ADR 0036), if tuning shows the difference matters
- [ ] Input: symmetric preferences, one relation per pair of workers (liked, disliked or neither), leaving it to
      whoever writes the input to decide how to read one-sided feelings; floated by the user while reading cards
      (2026-11-20). The audit meanwhile lets a dislike cancel the like it meets (ADR 0051)
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
