# Future work

Ideas and features that have been discussed and deliberately **deferred**; each item would get its own ADR when it's
taken up. Items are listed in priority order. Some have since been taken up, in whole or in part: their status notes
say so, and they keep the measurements and reasoning that led there.

When and in what order items are taken up is in the [Roadmap](../roadmap.md); each item deferred here is also listed
in its "Later" section.

## Schedule history

> [!NOTE]
> **Implemented** on 2026-11-12 ([ADR 0029](../decisions/0029-schedule-history-input.md),
> [ADR 0030](../decisions/0030-history-in-scoring.md), [ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md)),
> with the audit across schedules (Phase 7 of the [roadmap](../roadmap.md)). What's still open is below.

Without a history, every run creates a **new** schedule, in which every worker is "fresh". When schedules are created
for consecutive periods (typically 24–48 hours), this causes two problems at the boundary between periods:

* **Rest:** a worker who took the last shift of the previous schedule could be given the first shift of the new one,
  breaking the minimum rest period.
* **Fairness:** workload and rest fairness start over every period, so small imbalances can accumulate across
  schedules.

The solution: the input lists **previous schedules**, each as its input and its schedule file
([output](../reference/output-format.md#reading-the-output-back), which is designed to be read back). Their
assignments are **fixed**: the history is the already-filled first part of one schedule, which the search continues
and which is scored as a whole, from scratch, so the algorithm effectively *extends* the earlier schedules:

* the minimum rest holds across the boundary, as a hard constraint;
* workload is counted over the history and the new period together, relative to each worker's availability in
  each, so a worker who carried more before is given less now, and being away is never a debt;
* the rest after each worker's last history shift counts like any other.

Past short straws are partly compensated: each worker's rest shortfall is squared over the whole schedule, history
included ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)), so a worker who had short
rests is spared more of them. Disliked pairings aren't; making up for them across the parts of the penalty is
[deferred](#compensation-across-the-parts-of-the-penalty).

### A schedule that leaves the next one with no legal schedule

> [!WARNING]
> **Partially implemented.** Found on 2026-11-14. A schedule that leaves the next period **no** legal schedule is
> warned about since 2026-11-16 ([ADR 0042](../decisions/0042-warn-when-the-next-period-cant-be-filled.md)); one that
> leaves it a **worse** schedule, below, is still open.

The search finds the best schedule for its own period, with no regard for the period after it. A first period starts
with every worker rested, which the next one doesn't, and nothing tells the search that work in its last hours limits
who can start the next. In real use, that can be a schedule after which the next one can't be made.

**On the benchmark** (continued for a second day with the first as history, the inputs staffed at the minimum the
first day needs plus 1–2 workers), 6 of the 15 inputs first had no legal second day for some or all of the scorings
tried. Looked at again on 2026-11-15/16:
* **`sweep_01`, `sweep_03`, `sweep_04`:** a flaw in the test. These are 16-hour periods from 16:00 to 08:00, and the
  second ran from 08:00 to midnight, not the same schedule: 12 hours of a desk open 08:00–20:00, against 4 in the
  first. Since 2026-11-16 the second period covers the same hours, a whole number of days later (the user), and all
  three have a legal second day.
* **`sweep_05`, `sweep_09`** (20 hours): the end of the first day had used the holders of a role the gate needs at
  night, so the second day, starting right after, was stuck at its first slot. Starting at the same hours a day later,
  4 hours after the first ends, they have a legal second day.
* **`sweep_08`** (24 hours, so the next day starts right after): the same, at midnight, with the medics; both days
  planned as one schedule could be filled. It's the one benchmark input, at the defaults, the warning catches.
* **The example** (`exampleInput.yml`, 24 hours) does the same with the security holders the front gate needs at night.

**The decision** (the user, 2026-11-15/16): **warn**, as long as it's computationally cheap, with the next period
assumed to have exactly the same parameters, at the same hours a whole number of days later. Done in
[ADR 0042](../decisions/0042-warn-when-the-next-period-cant-be-filled.md): after writing a schedule, the command line
searches for any legal schedule of the next period, with this one as history, within about 500,000 nodes (a few
seconds at most), and warns if there's none, or notes that it couldn't tell. The tuning still counts a setting whose
first day leaves no legal second day as a failure.

A milder form (2026-11-14): a first period that leaves the next a worse schedule than another first period would
have. On `sweep_02`, with the workload weight raised from 0.38 to 1.0, the first day's best schedule no longer had an
avoidable gap of two shifts, but the second day continued from it had 17 complaints with an easy fix instead of none.
From the same first day, every setting gave the same second day, so the difference came from the first day alone; by
the 1.0 setting's own scoring, the two days together were better continued from the 0.38 setting's first day, gap and
all. The best schedule for each period isn't always the best start for the next.

## Explaining infeasibility

> [!WARNING]
> **Not yet implemented.**

When no legal schedule exists, TinyScheg reports that and produces no output (see
[ADR 0011](../decisions/0011-no-output-for-infeasible-inputs.md)). It would help to also say **why**. Cheap checks
before the search can catch many causes, e.g. a slot whose domain is empty right after availability and role
pruning ("no worker with the supervisor role is available on 2025-01-02 04:00–07:00").

Reporting the slots no worker can fill, and the point at which the search ran out of options, is decided
([ADR 0020](../decisions/0020-report-where-infeasibility-was-found.md)). What remains here is a fuller explanation:
further cheap checks (e.g. a shift needing more distinct workers than its slots' domains hold together), or a
minimal set of conflicting requirements.

## Search performance

> [!IMPORTANT]
> **Partially implemented.** Cheapest-first value ordering and a lower bound on workload were implemented on
> 2026-11-11 ([ADR 0024](../decisions/0024-cheapest-first-value-order-and-workload-bound.md)), when search speed
> blocked [tuning](tuning.md), and on 2026-11-12, symmetry breaking within shifts
> ([ADR 0025](../decisions/0025-order-interchangeable-slots.md)) and look-ahead bounds for likes and workload, and on
> 2026-11-15 a workload bound in whole slots ([ADR 0040](../decisions/0040-workload-bound-in-whole-slots.md)). The
> rest below is deferred. Branch and bound runs
> to the end with no limit; it shows its progress, and Ctrl+C stops it, keeping the best schedule found so far
> ([ADR 0035](../decisions/0035-search-progress-and-keeping-the-best-on-interrupt.md)).

Measured on the example on 2026-11-11, with prototypes in which each idea was checked against brute force on small
inputs (before ADR 0024, branch and bound proved the best 24-hour schedule, 17 slots, in about 200 s, but didn't
finish a 48-hour one, 32 slots, in 5 minutes, nor a 72-hour one, 47 slots, in 10):

| Prototype | 24 h: time to prove the best | 48 h: best after 5 min | 72 h: best after 60 s |
|---|---|---|---|
| Before ADR 0024 | 202 s | 2.70 | 3.28 |
| Stronger workload bound | 49 s | 2.70 | 3.22 |
| Cheapest-first value ordering | more than 300 s | 2.54 | 2.90 |
| Both (as implemented) | 93 s | 2.53 | 2.90 (after 1.5 s) |
| Symmetry breaking | — | — | 3.28 |

As implemented then, the command line proved the 24-hour example in about 100 s. Cheapest-first finds good schedules
far sooner, but costs time per step, so on some inputs the bound alone would be faster. Neither finished a 48-hour
schedule. (On 2026-11-15, with everything below and the weights of ADR 0039, the 24-hour example took about 30 s,
9 s on PyPy, in one process, and about 20 s, 5½ on PyPy, with the cheaper bound below; the 48-hour example still
didn't finish in 15 minutes, its progress estimating about an hour. In parallel,
[ADR 0041](../decisions/0041-parallel-search-with-the-sequential-result.md), it takes about 12 minutes on PyPy, its
best schedule found at 9½.)
Still deferred:

* **Symmetry breaking between workers.** Within a shift it's done (ADR 0025): on the one benchmark input with
  interchangeable slots, 43 times fewer nodes (174 s down to 4.5 s); none of the example's shifts have any. Two
  workers identical in every respect (roles, availability, their likes and dislikes, and everyone else's of them)
  could be ordered too, but that's rare and easy to get subtly wrong. Shifts are never interchangeable: in asymmetric
  schedules they differ in length, rest targets and availability.
* **Tighter bounds.** Done on 2026-11-12 for likes (each pair of slots in a shared shift adds at least the cheapest
  pairing its domains allow) and workload (each worker gains at most the hours of the slots they could take). Measured
  on the example and the 15 benchmark inputs, with the best penalty unchanged on every one:

  | | Total time | Nodes | 24-hour example |
  |---|---|---|---|
  | ADR 0024 only | 1172 s | 27.3 M | 168 s |
  | + symmetry within shifts (ADR 0025) | 1027 s | 24.3 M | 172 s |
  | + workload caps only | 1240 s | 24.3 M | 161 s |
  | + likes look-ahead only | 540 s | 9.8 M | 10.5 s |
  | + both (as implemented) | 117 s | 2.8 M | 7.1 s |

  (Run 12 at a time, so times are noisy; node counts aren't. Alone, the caps cost more than they save; with the
  likes look-ahead, they cut the nodes by another 3½ times.)

  Done on 2026-11-15: a workload bound in whole slots
  ([ADR 0040](../decisions/0040-workload-bound-in-whole-slots.md)). Water-filling spreads the remaining work as if
  it could be split finely, and the workload weight multiplies that gap: raising the weight from 0.38 to 1.0
  (2026-11-14) took the search to about 4.5 times the nodes on the tuning inputs (15.6 M to 70 M). Measured, almost
  all of the slack was whole slots; roles and rest between the unfilled slots added about nothing. With the bound,
  every benchmark input gives the same schedules, alone and as day 2, with 3–75 times fewer nodes (see the ADR);
  `confirm_01` takes 4½ minutes instead of 2 hours.

  Done on 2026-11-15, without changing a decision: the whole-slot estimate then cost most of the search's time (76%
  on CPython on the example, 33–56% on PyPy), and at 17–54% of the nodes checked against the pocket, the bound
  without it already pruned. The search now checks that cheaper bound first, computed with the same expression so
  that it's never above the full one, and skips the whole-slot estimate where it already prunes; the estimate's
  inner loop was also rewritten for speed, with the same arithmetic. Every node and schedule stayed exactly the same
  (37 inputs traced, byte for byte); about 1.8 times faster on CPython (the example 31 s to 18 s), and 1.0–1.3 times
  on PyPy, varying from run to run with its just-in-time compiler.

  Still open: a rest look-ahead (none is valid that's cheap, since a worker can always get no further shifts), caps
  that account for overlapping slots, and whole-slot sets per worker that count only the slots in their own domains
  (tighter, but they'd have to be kept up to date as forward checking narrows the domains).
* **A limit.** Stop the search after a given time or number of nodes and return the best pocket schedule found so
  far. A node limit keeps the result deterministic; a time limit makes it depend on the machine. With either, value
  ordering affects the *result* and not just the speed. Decided against (2026-11-11, confirmed 2026-11-12): long
  runs for a single schedule aren't to be forbidden in real use, so the search runs to the end. Instead, since
  2026-11-14 ([ADR 0035](../decisions/0035-search-progress-and-keeping-the-best-on-interrupt.md)), it shows its
  progress with a rough time left, and Ctrl+C stops it, writing the best schedule found so far: stopping is the
  user's choice, made with the progress in view.

### Speeds on the two machines (2026-11-16)

Every timing above, and in the rest of the docs up to 2026-11-15, was measured on a desktop with a Ryzen 7 5800X3D
(8 cores, 16 threads, 96 MB of cache). Development moved to a laptop with a Ryzen AI 9 HX 370 (12 cores, 4 full and 8
compact, 24 threads, 24 MB of cache), which is the working machine from now on, so it was measured again on the
current code, with the same schedules and node counts on every input (archived outside the repository):
* **In one process,** the laptop is faster: about 1.6 times on PyPy (the example 3.3 s against 5.1–5.5 s) and 1.35
  times on CPython (13.8 s against 18.7 s).
* **In parallel,** it's held back by heat (its processor stays at its 95 °C limit): `confirm_01` takes about 25 s
  with 12 or 16 processes, as on the desktop with 16, but about 35 s with 24, one per logical processor, which is
  the default ([ADR 0041](../decisions/0041-parallel-search-with-the-sequential-result.md)). On the desktop, the
  second thread of each core gained little and cost nothing; here it costs a third. Timings vary by up to 15% from
  run to run.
* **The benchmark inputs,** with 12 processes: each under 25 s, alone and as a second period.
* **The 48-hour inputs,** with 12 processes, and when the best schedule was found:

  | Input | First 48 hours (desktop, 16 processes) | Best found after | Second 48 hours (desktop) |
  |---|---|---|---|
  | `multiday_01` | 372 s (387 s) | 2 s | 8 s (11 s) |
  | `multiday_02` | 94 s (98 s) | 39 s | under 1 s |
  | `multiday_03` | 363 s (367 s) | 19 s | 27 s (29 s) |
  | `multiday_04` | 1,189 s (1,247 s) | 196 s | 150 s (157 s) |
  | `multiday_05` | 3,107 s (3,224 s) | 132 s | 505 s (364 s) |

  The best schedule was found within the first 41% of each first period's search, mostly far sooner; every search
  had a schedule within 1% of the best penalty within 2 seconds, and within 0.1% within 40. The rest of the time
  proves nothing beats it. The penalty's share isn't a measure of fairness, though: the schedules found early weren't
  audited.

## Faster search by non-heuristic means

> [!NOTE]
> **Done, as far as it's worth going** (2026-11-15). Deferred 2026-11-12; PyPy adopted for development runs on
> 2026-11-13 ([ADR 0033](../decisions/0033-pypy-for-development-runs.md)); parallel search on 2026-11-15
> ([ADR 0041](../decisions/0041-parallel-search-with-the-sequential-result.md)), and the same day the bound without
> its whole-slot part checked first ([Search performance](#search-performance)). A compiled core and domains as
> bitsets were decided against for now (below). Still open: measuring parallel search where processes are spawned
> (below).

Everything under [Search performance](#search-performance) speeds the search up by searching smarter: finding a good
pocket sooner, or pruning more. The other way is to run the same search faster, without changing what it explores:

* **Libraries**, such as a compiled numeric library for the scoring, or a constraint or optimization solver.
* **Parallelization**, such as splitting the search tree between processes, which then share the pocket's penalty
  so that each prunes on the best found by any. *Done on 2026-11-15*
  ([ADR 0041](../decisions/0041-parallel-search-with-the-sequential-result.md)): with the subtrees numbered in the
  sequential order and that number deciding ties, the schedule is the same as in one process, and 8 processes ran
  about 7.6 times faster on 8 cores. Still to measure: where processes are spawned rather than forked (Windows,
  macOS), each loads and warms up on its own, a cost short runs would feel; it should be measured there, and the
  default reconsidered if need be, before [distribution](#accessibility-for-non-technical-users).
* **Rewriting the hot modules in another language**, such as the search and scoring in a compiled language, called
  from Python. *Decided against for now (2026-11-15).* It's the one option with much potential left, but it needs a
  build toolchain, either gives up PyPy or keeps two implementations, complicates the simple
  [distribution](#accessibility-for-non-technical-users) wanted, and would have to match Python's arithmetic exactly
  for the results to stay the same. The profile then showed one hot function (the whole-slot estimate), since made
  cheaper, rather than a slow language throughout; with the example taking about 2 seconds in parallel, and long
  schedules limited by how much is pruned rather than by the cost of each node, it isn't worth that cost. To be
  reconsidered only if a real need appears that pruning can't meet.

Any of these must keep the result deterministic and exactly the same (the same best penalty, and the same schedule
among equally good ones, or a rule for which one is kept), and adding a library needs the usual justification
(see the project's working rules). Profiling first would show where the time actually goes (when this was written,
the penalty and bound were computed from scratch at every node; they're now kept incrementally, see
[Incremental scoring](#incremental-scoring)).

Profiled on 2026-11-13: on the slower inputs, the search finds its best schedule within the first 10% of the run
(59% at most); the rest is proving that nothing beats it, so a better first pocket would hardly help. A table of every
pair's like value, computed once instead of at every step of the likes look-ahead, was then done in plain Python: on
the example and the 15 benchmark inputs, the same nodes, penalties and schedules, 1.12 times faster in total
(568 s to 508 s; 1.0–1.5 times per input).

PyPy, tried on 2026-11-13 (PyPy 3.11, v7.3.23, from pypy.org; conda-forge's stops at Python 3.9, which the code can't
run on): the code and its libraries run unchanged, and the search is about 3 times faster on the same inputs. Its
results first differed in the last digits, and on 3 inputs it kept a different one of two exactly tied schedules:
`sum()` rounds differently on CPython 3.12+ (which compensates) than on 3.11 and PyPy. The scoring now adds lists of
floats with `math.fsum`, which rounds only once: CPython's results stayed exactly the same, its time too (513 s), and
PyPy's became identical to CPython's, in 190 s (2.7 times faster; `fsum` costs PyPy about a tenth).

Experiments on 2026-11-13, each checked for exactly the same nodes, penalties and schedules on the example and the 15
benchmark inputs, under CPython and PyPy:

* **Kept:** cheaper bookkeeping per node (the next slot chosen in one pass, a worker dropped from a domain by slicing,
  the undo record keeping a position instead of a copy of the worker's slots) and plain loops instead of `fsum` in the
  incremental totals, which only steer: 1.08 times faster on CPython, 1.22 on PyPy.
* **mypyc** (compiling `csp/` and `scoring/` to C extensions): 2.34 times faster than CPython, after small
  type-annotation edits; compiling `model/` too broke input validation (compiled classes check argument types
  strictly). Slower than PyPy and a build step after every change, so not adopted; an option for a CPython
  distribution.
* **No gain:** stopping the likes look-ahead's minimum at the lowest possible value (1.02 times); recomputing only the
  look-ahead's pairs that touch the changed slot (nothing to gain: every shared shift in the benchmark has two slots,
  so one pair); workload caps that account for overlapping slots (up to 23% fewer nodes, but 0.94 times on CPython,
  since the caps rarely bind: the workload bound's looseness is elsewhere); symmetry between identical workers (only
  3 of the 16 inputs have even one identical pair).

Final comparison (3 rounds, per-input medians): CPython 509 s, CPython with mypyc 218 s, PyPy 156 s, all with the
kept changes but the first, which is CPython before them.

An optional idea, not tried (2026-11-14): **domains as bitsets.** Each slot's domain, the workers who can still fill
it, held as the bits of one integer instead of a tuple: dropping a worker is one operation, a domain's size (for
choosing the next slot) a bit count (`int.bit_count()`), and an emptied domain a test for zero, so many workers are
handled per machine instruction. Python integers do this well and PyPy compiles it to tight code, unlike a numeric
library such as NumPy, which pays a fixed cost per call that's larger than the work on arrays this small, and is
slow on PyPy. Whether it pays off has to be measured: domain handling is only part of the cost per node, the
incremental scores being the other large part. *Decided against (2026-11-15):* profiled, forward checking was 4–7%
of the time on PyPy and choosing the next slot 1–2%, so even a large gain there would be worth perhaps 5–10% in
all, against rewriting every domain operation and its undo.

## Incremental scoring

> [!NOTE]
> **Implemented** on 2026-11-12 ([ADR 0027](../decisions/0027-incremental-scoring-for-steering.md)).

Penalties are first computed from scratch for every state. Updating them incrementally would be faster, but must
stay exactly path-independent (see [ADR 0012](../decisions/0012-deterministic-path-independent-scoring.md)), for
example by using exact arithmetic. The from-scratch computation then serves as a test oracle.

Done on 2026-11-12 ([ADR 0027](../decisions/0027-incremental-scoring-for-steering.md)): incremental totals only
to steer the search (the value order, and pruning away from near-ties), with near-ties and complete schedules scored
exactly from scratch, so that the result stays exactly the same. On the example and the 15 benchmark inputs, the same
nodes, penalties and schedules, 1.7 times faster overall (1.1–3.1 times per input); computing the water level in one
sweep instead of from every breakpoint was part of it. No single hotspot remains: what's left is spread over the
incremental updates, the workload bound's pool and the search's own bookkeeping, which tuning the Python (see
[Faster search by non-heuristic means](#faster-search-by-non-heuristic-means)) could still speed up.

## Dangling shifts

> [!WARNING]
> **Not decided.** Deferred (2026-11-10, when TinyScheg didn't yet run end to end; it does now).

When a segment's length isn't a multiple of the shift length, its last shift is cut short
([ADR 0018](../decisions/0018-slot-generation-by-segments.md)). This is expected to be rare in real use. Options if it
needs handling: keep the short shift (current behaviour), merge it into the previous shift, or let the input set a
minimum shift length. If the segment scheme itself doesn't work well in practice, it will be revisited.

## Time and post preferences

> [!WARNING]
> **Not yet implemented.** Low priority.

Workers' preferences currently concern only other workers (likes and dislikes). They could be extended to
preferences about *when* or *where* they work, e.g. avoiding mornings or preferring a particular post. These would
be additional, monotone penalty components.

## Forcing a worker into a shift

> [!WARNING]
> **Not yet implemented.** Low priority; deferred 2026-11-12.

Letting the input name a worker who must fill a particular shift (for example, someone who has to be at a post at a
certain time), as a hard constraint rather than a preference. The machinery exists since
[ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md): such a slot could be filled before the
search starts, like a history slot, with forward checking from it, and the scoring would count it like any other.
Open: how the input names the shift (post and start time) and the role if the shift has several slots, and what to
report when the forced assignment itself breaks a hard constraint (the worker unavailable, without the role, or too
close to another forced shift).

## Spreadsheet presentation

> [!WARNING]
> **Not yet implemented.** Low priority.

* **Right-to-left sheets.** XLSX and ODS sheets can be displayed right to left, as rosters in Hebrew and other
  right-to-left languages usually are, e.g. through an input setting. Output is left to right for now.
* **Roles in the output.** The grid doesn't show which worker fills which role. Cells could show it, e.g.
  `Jack (security)`.

## A fairness term for liked pairings

> [!WARNING]
> **Not yet implemented.** The alternative not taken, 2026-11-11; revisit if the
> [choice made instead](schedule-audit.md#liked-partner-complaints-are-counted-apart) turns out wrong.

The likes penalty rewards the total of liked pairing, not how evenly it's spread, so the best schedule can leave one
worker never sharing a shift with anyone they like while a pair of friends share several. The audit counts such
liked-partner complaints apart instead of fixing them through tuning. If they turn out to matter, the fix is in the
formula: each worker's shortfall of liked pairings through a convex function, as workload does, which needs an ADR,
a check that the penalty stays monotone along the search, and new tuning runs.

## Compensation across the parts of the penalty

> [!WARNING]
> **Not yet implemented.** Deferred on 2026-11-14, until the weights had been checked again; they have since
> ([ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)).

The user (2026-11-14): a shift with someone a worker likes "is in and of itself making up for drawing the short
straw": a liked pairing can make up for one short rest, or for being the one who has to take the extra shift in an
unavoidable 2-2-3, and a dislike likewise justifies being screwed over once, but no more. The user hoped this would
arise from the penalties' convexity.

It arises only *within* a part: each worker's workload, and each worker's rest shortfall, go through their own convex
function, so a worker who already has more of either is spared more of the same. *Across* parts it doesn't: each part
is convex separately, and the likes part is a plain sum over pairings, so a like is worth the same whoever gets it,
and the model has no reason to give it to the worker who drew the short straw. Where the extra shift can itself be the
one with a friend, the model picks that; where the liked pairing is elsewhere, it doesn't care who gets it.

For compensation to arise naturally, each worker's parts would go through **one** convex function: their rest
shortfall and the cost of their pairings (and perhaps their workload) added up per worker first, then made convex,
so that sparing a worker whose total is already high is worth more. It stays monotone, as branch and bound needs,
since a liked partner adds nothing where a neutral or disliked one adds a cost. The parts' units would have to be made
commensurate within each worker's total, rather than only weighed against each other in the sum, and the workload's
availability-relative form fitted in. It needs an ADR, new provable properties and tuning again. Related:
[a fairness term for liked pairings](#a-fairness-term-for-liked-pairings), the likes-only version of the same idea.

## Workload in hours only

> [!WARNING]
> **Not yet implemented.** Deferred on 2026-11-14.

The workload part counts shifts as well as hours: the shift share $\sigma$ blends each slot's hours with one average
slot ([ADR 0026](../decisions/0026-workload-counts-shifts-and-hours.md)), an exchange rate between shifts and hours
set by hand, which the user would rather not set. It was added when the rest part ignored the rest after a short
shift, so nothing kept one worker from being given several short shifts while another had one long one at the same
hours. The user (2026-11-14) would measure workload only as the hours worked over the hours available, and leave
spreading shifts out to rest; of two workers like those below, the one who worked more hours drew the short straw,
and even when that was unavoidable it has to count, so that it can be made up for later.

The rest part ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)) gives each rest a
target in proportion to the two shifts around it, and nothing for rest beyond it. In tight schedules the target
between two short shifts sits at or near the minimum rest (between two 2-hour shifts, 6 hours, the minimum itself, on
`sweep_02`; 6.85 on `sweep_11`), so there rest can't keep short shifts apart, and with hours alone nothing else does.
On `sweep_11` over two days, $\sigma = 0$ gave one worker five 2-hour shifts (10 hours) with rests of 6–8 hours, and
another two 4-hour shifts (8 hours) with one rest of 16: hours alone see the 2 extra hours, but not that they came as
three more, shorter shifts with shorter rests. At $\sigma = 0.5$, every fully available worker had 3 or 4 shifts. So
$\sigma$ stays at 0.5 until the rest part keeps short shifts apart in tight schedules too; then it could go to 0.

Counting shifts also works the other way round, with a [dangling shift](#dangling-shifts) (`sweep_06`,
2026-11-14). One worker has a 6-hour shift and a 1-hour shift left over at the end of the period, 7 hours against a
peer's 4, where an even share is 5. Moving the 1-hour shift to the peer evens the hours, but at $\sigma = 0.5$ it
counts as 1.8 hours, and as a whole extra shift for the peer, so the model keeps it where it is, at every weight
tried; at $\sigma = 0$ it moves it. All 12 of that input's complaints with an easy fix are this one move.

## Tuning on longer schedules

> [!NOTE]
> **Done** on 2026-11-16 ([the 48-hour check](tuning.md#the-48-hour-check-2026-11-1516)): the defaults hold on 48
> hours, for now.

The defaults were tuned on schedules of 16 to 24 hours ([ADR 0028](../decisions/0028-rest-factor-default-2-5.md),
[ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)), the longest branch and bound could finish
then, and on those the whole schedule is the day. With the parallel search
([ADR 0041](../decisions/0041-parallel-search-with-the-sequential-result.md)), the multiday tier's 48-hour inputs
could be searched, and the defaults were checked on them: load within a day, the reason for the check, was uneven
only where a long rest fell, with even totals, which the user considers fair; the audit gained a correction. Left
open: about half the generated 48-hour inputs took over half an hour to search, some much longer.

## Schedule audit

> [!WARNING]
> **Not yet implemented.** Low priority; deferred 2026-11-11.

* **Samples with no easy fix at all.** In one sample of the example (seed 16 of `tools/audit_sample.py`, 2026-11-11),
  none of its 74 complaints had an easy fix, though most samples have many. With the audit and search of 2026-11-15,
  seed 16 has fixes, but 4 of 200 samples have none (seeds 150, 165, 174 and 190; seed 150 has 18 complaints). Worth
  finding out why: whether the greedy chain search misses fixes there, or the schedule really has none.

## Documentation

> [!WARNING]
> **Not yet implemented.** Low priority.

* **Tutorials**, now that TinyScheg runs end to end.
* **A generated API reference** (e.g. mkdocstrings), replacing the hand-written pages in `docs/reference/api/`.
* **Publishing the docs site**, e.g. to GitHub Pages.

## Accessibility for non-technical users

> [!WARNING]
> **Not yet implemented.** Lowest priority: these are for once TinyScheg is finished and working, to make it usable
> by people who don't work with the command line.

* **An optional graphical interface.** A GUI for people put off by the command line, alongside the command-line
  interface rather than replacing it.
* **Simple distribution.** Per platform, something that needs no installation of Python or other dependencies, and
  can be used either from the command line or through the GUI. Windows and Linux versions, and possibly a macOS
  version. It needn't be a single file (the user, 2026-11-13), but a non-technical user must be able to just click one
  obvious file to run it. One option is a folder with a portable PyPy inside (about 3 times faster than CPython on
  the search, measured 2026-11-13) and a launcher; another is a CPython bundle (PyInstaller, Nuitka, or the Windows
  embeddable Python), which those tools support and PyPy doesn't.
