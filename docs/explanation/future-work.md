# Future work

Ideas and features that have been discussed and deliberately **deferred**. Nothing on this page is implemented or
decided; each item would get its own ADR when it's taken up. Items are listed in priority order.

When and in what order items are taken up is in the [Roadmap](../roadmap.md); each item deferred here is also listed
in its "Later" section.

## Schedule history

> [!WARNING]
> **Partially implemented.** Built on 2026-11-12 ([ADR 0029](../decisions/0029-schedule-history-input.md),
> [ADR 0030](../decisions/0030-history-in-scoring.md), [ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md));
> the audit across schedules is still to come (Phase 7 of the [roadmap](../roadmap.md)).

Currently every run creates a **new** schedule, in which every worker is "fresh". When schedules are created for
consecutive periods (typically 24–48 hours), this causes two problems at the boundary between periods:

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

Past short straws (disliked pairings, short rests) aren't compensated by this; whether they need to be is for the
audit across schedules to show (ADR 0030).

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
> ([ADR 0025](../decisions/0025-order-interchangeable-slots.md)) and look-ahead bounds for likes and workload. The rest
> below is deferred. Branch and bound runs
> to the end with no limit and can be interrupted with Ctrl+C.

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

As implemented, the command line proves the 24-hour example in about 100 s. Cheapest-first finds good schedules far
sooner, but costs time per step, so on some inputs the bound alone would be faster. Neither finishes a 48-hour
schedule. Still deferred:

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
  likes look-ahead, they cut the nodes by another 3½ times.) Still open: a rest look-ahead (none is valid that's
  cheap, since a worker can always get no further shifts), and caps that account for overlapping slots.
* **A limit.** Stop the search after a given time or number of nodes and return the best pocket schedule found so
  far. A node limit keeps the result deterministic; a time limit makes it depend on the machine. With either, value
  ordering affects the *result* and not just the speed. Decided against (2026-11-11, confirmed 2026-11-12): long
  runs for a single schedule aren't to be forbidden in real use, so the search runs to the end, and Ctrl+C stops it
  without writing anything. Run times are watched during development instead.

## Faster search by non-heuristic means

> [!WARNING]
> **Not yet implemented.** Deferred 2026-11-12.

Everything under [Search performance](#search-performance) speeds the search up by searching smarter: finding a good
pocket sooner, or pruning more. The other way is to run the same search faster, without changing what it explores:

* **Libraries**, such as a compiled numeric library for the scoring, or a constraint or optimization solver.
* **Parallelization**, such as splitting the search tree between processes, which then share the pocket's penalty
  so that each prunes on the best found by any.
* **Rewriting the hot modules in another language**, such as the search and scoring in a compiled language, called
  from Python.

Any of these must keep the result deterministic and exactly the same (the same best penalty, and the same schedule
among equally good ones, or a rule for which one is kept), and adding a library needs the usual justification
(see the project's working rules). Profiling first would show where the time actually goes: most of it is probably
the penalty and bound, computed from scratch at every node (see [Incremental scoring](#incremental-scoring)).

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
> **Not decided.** Deferred until TinyScheg works end to end.

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

## Tuning on longer schedules

> [!WARNING]
> **Not yet done.** Deferred 2026-11-12, until the search can finish 48-hour inputs.

The defaults were tuned on schedules of 16 to 24 hours ([ADR 0028](../decisions/0028-rest-factor-default-2-5.md)),
the longest branch and bound could finish. On those, the whole schedule is the day, so the audit's comparison of load
in any 24 hours adds nothing to its overall comparison. Whether the scoring keeps load even within each day of a
longer schedule, as well as overall, can only be checked on 48-hour inputs (the multiday tier, dropped for now). The
check: generate the tier, run the defaults on it, and see whether day-load complaints with an easy fix appear.

## Schedule audit

> [!WARNING]
> **Not yet implemented.** Low priority; deferred 2026-11-11.

* **Samples with no easy fix at all.** In one sample of the example (seed 16 of `tools/audit_sample.py`), none of
  its 74 complaints had an easy fix, though most samples have many. Worth finding out why: whether the greedy chain
  search misses fixes there, or the schedule really has none.

## Documentation

> [!WARNING]
> **Not yet implemented.** Low priority.

* **Tutorials**, once TinyScheg runs end to end.
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
