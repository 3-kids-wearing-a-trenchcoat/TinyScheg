# Schedule audit

The schedule audit is a **development tool**: it judges a finished schedule the way its workers would, to check that
the [scoring](scoring.md) and its tuning don't produce schedules that workers would rightly complain about, such as
unfairness concentrated on a few workers. It isn't part of TinyScheg's regular operation.

> [!WARNING]
> **Not yet implemented.** This page is the agreed specification (2026-11-11); the audit is being built in
> `tools/` (see the [Roadmap](../roadmap.md#phase-4-schedule-audit-development-tool)).

## Why a separate audit

The internal penalty has to be cheap, monotone along the search and normalized, so it's a compressed summary of
fairness. The audit has none of those constraints: it can be slow and detailed, and it describes each worker's
experience in the terms workers actually use. Comparing the two shows where the summary misses something.

To keep the comparison meaningful, the audit is **independent**: it uses `tinyscheg.model` and `tinyscheg.parsing`
to read the input and list the shifts, the written schedule file for the assignment
([`tools/schedule_reader.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/tools/schedule_reader.py)),
and the independent hard-constraint checker
([`tools/schedule_checker.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/tools/schedule_checker.py))
for legality — and nothing from `csp/` or `scoring/`. A bug or blind spot there can't hide the same one here.

## How workers judge a schedule

The audit is built on how workers actually react to a schedule:

* **Relative, not absolute.** Workers compare themselves with each other: not "why do I have three shifts today?"
  but "why am I doing three shifts today when X only does two?".
* **Unavoidable unevenness is tolerated.** If everyone does two shifts and one worker does three, someone had to.
  If everyone does two and one worker does four, that's an outrage: it could have been two workers doing three.
* **Complaints aren't a failure in themselves.** Most are unavoidable. Complaints that could have been fixed
  **easily**, such as by swapping two workers' posts in the same hour, are what's bad.
* **The short straw.** Workers accept that someone has to get the bad end of a schedule, but are very sensitive to
  getting it **more often** than others.

Every shift counts the same, whatever the time of day: the audit, like the scoring, makes no distinction between day
and night shifts.

## Complaints

Every criterion produces **complaints**, each by one worker (A) against another (B) about one measure, over one
window of time:

* **Peers.** A complains about B only if B was **available at least as long** as A during the window, and for some
  time at all: B had no excuse.
* **Tolerance.** A complains only if A's measure exceeds B's by **more than** `TOLERANCE` (1). One extra is
  tolerated; two is a complaint.
* **Severity** is how far the gap goes past the tolerance: a gap of 2 has severity 1, a gap of 3 severity 2.
* **Roles aren't considered** when finding complaints. A worker carrying more because few others have a role still
  complains; whether anything could have been done is the question of [avoidability](#avoidability).

A worker's availability during a window is the part of the window inside the period, minus their unavailability.

### Load

Load is compared per **day** and over the **whole period**:

* **Days** run from `DAY_BOUNDARY` (midnight) to the next; a shift belongs to the day it starts on. Days are only
  counting windows.
* Load is measured both in **shifts** and in **hours**, and the gap is taken in shifts: the larger of the difference
  in shifts and the difference in hours divided by the longest shift in the window. That keeps "one extra shift"
  tolerated even when posts have different shift lengths.

For example, if A did 4 shifts of 4 hours on a day and B, available all that day, did 2, the gap is 2 and A has a
complaint of severity 1 against B.

### Short straws

A **short straw** is a bad draw. Each worker's short straws over the whole period are counted, and compared between
peers (available at least as long over the whole period) with the same tolerance:

* **Short rest** — a rest between two of the worker's shifts that's shorter than `min_rest + SHORT_REST_MARGIN`
  (2 hours): close to the legal minimum.
* **Heaviest day** — having the most shifts of anyone available on a day, when not everyone available did the same
  number.
* **Disliked partner** — each shift shared with a worker they dislike.

### Pairings

* Every shift a worker shares with someone they dislike is listed on their card (and counts as a short straw).
* Among workers who like anyone, A complains about B if B shared shifts with someone they like more often than A did,
  by more than the tolerance (peers over the whole period, as above).

## Avoidability

A complaint is **avoidable** if one simple, legal change to the schedule fixes it:

* **Move** — give one slot to a different worker.
* **Swap** — two workers exchange slots, such as two posts in the same hour.

The change must be legal (checked by the hard-constraint checker), remove the complaint, **create no new complaint
and make no existing complaint more severe**, for anyone. Otherwise it only moves the problem around. The card names
the change, e.g. "giving Bob front gate 2025-01-01 04:00–08:00 would fix this".

Each candidate change is audited in full, which is slow but straightforward.

## The report

* A **card per worker**: their shifts and hours (per day and overall) against their availability, their shortest
  rests, their short straws, who they shared shifts with, and their complaints, most severe first, each saying
  whether and how it's avoidable.
* A **group summary**: the number of complaints; the total severity of the avoidable ones and of the unavoidable
  ones; how many workers have any complaint; and **concentration**, the share of all severity held by the worker
  with the most, with the workers ranked by severity.

## Sampling

To compare the audit with the internal penalty, the sampler makes many legal schedules for one input by shuffling the
workers' order before the search, then audits and scores each. It reports:

* the **rank correlation** (Spearman) between the internal penalty and the total avoidable severity;
* **disagreements**: the schedules among the best by internal penalty that have the most avoidable severity, with
  their summaries.

Until [branch and bound](search-algorithm.md#branch-and-bound-the-pocket) exists, these are first legal schedules,
not a random sample of all legal ones, which is enough to find blind spots.

## Parameters

Named constants at the top of the audit's code: `TOLERANCE` (1), `DAY_BOUNDARY` (00:00), `SHORT_REST_MARGIN`
(2 hours). They're the audit's own, and unrelated to the [scoring parameters](scoring.md#parameters).
