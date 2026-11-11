# Schedule audit

The schedule audit is a **development tool**: it judges a finished schedule the way its workers would, to check that
the [scoring](scoring.md) and its tuning don't produce schedules that workers would rightly complain about, such as
unfairness concentrated on a few workers. It isn't part of TinyScheg's regular operation.

> [!NOTE]
> **Implemented** in `tools/audit.py` and `tools/audit_sample.py`, and covered by tests. See
> [Auditing a schedule](../how-to/audit-a-schedule.md) for how to run it.

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
  complains; whether anything could have been done is the question of [easy fixes](#easy-fixes).

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
* **Disliked partner** — each shift shared with a worker they dislike.

Having the most shifts on a day isn't a short straw: [load](#load) already compares per-day load, with the same
tolerance. Counting it again would count one extra shift twice, since two shifts on one day usually also mean a short
rest: a worker with two close shifts would be 2 straws ahead of a peer with one shift, a complaint, although the load
gap of one shift is tolerated. (An earlier version did count it, and the first tuning baseline was dominated by such
complaints.)

### Pairings

* Every shift a worker shares with someone they dislike is listed on their card (and counts as a short straw).
* Among workers who like anyone, A complains about B if B shared shifts with someone they like more often than A did,
  by more than the tolerance (peers over the whole period, as above).

## Easy fixes

Every complaint is checked for an **easy fix**: a short chain of simple, legal changes that removes it. A complaint
with an easy fix is one workers would rightly hold against the schedule; for one without, **no easy fix was found**,
which doesn't prove there's none, only that none was found quickly. The simple changes are:

* **Move** — give one slot to a different worker.
* **Swap** — two workers exchange slots, such as two posts in the same hour.

A chain has at most `MAX_CHANGES` (3) changes. Each must be **legal** and **harmless**. The audited schedule itself
is checked once by the independent hard-constraint checker; after that, a change can only break a rule through what
it changes, so only that is checked: the roles and availability of the slots it gives away, and the rests of the
workers receiving them (a rest below zero is an overlap). A test confirms this always agrees with the full checker.
Harmless means: compared with the audited schedule, it creates no new complaint and makes no existing complaint more
severe, for anyone. Otherwise the fix only moves the problem around.

Chains are found greedily, which keeps the search quick:

1. First, every single change is tried, and each complaint a harmless one removes gets it as its fix.
2. Then, for each complaint left, most severe first, the harmless change that lowers its severity most is taken, then
   the next from there, until it's removed or `MAX_CHANGES` changes are made. A wide gap needs several moves:
   six shifts against none narrows by two with each move, so it takes three. A chain found for one complaint is also
   given to every other complaint left that it removes.

The card names the changes, e.g. "easy fix: giving Siduri front gate 2025-01-01 07:00–10:00 instead of Jack, then
giving Shamhat front gate 2025-01-02 07:00–10:00 instead of Jack".

Each candidate change is audited in full, which is slow but straightforward.

## The report

* A **card per worker**: their shifts and hours (per day and overall) against their availability, their shortest
  rests, their short straws, who they shared shifts with, and their complaints, most severe first, each with its
  easy fix, if one was found.
* A **group summary**: the number of complaints and how many have an easy fix; the total severity of those with an
  easy fix and of those without; how many workers have any complaint; and **concentration**, the share of all severity held by the worker
  with the most, with the workers ranked by severity. All of these leave out liked-partner complaints, which are
  counted apart (below).

### Liked-partner complaints are counted apart

Decided 2026-11-11, during the tuning baseline. Liked-partner complaints are still listed on the cards, with their
easy fixes, but the summary's main measures (and so tuning's priorities) leave them out; their number and severity are
reported on a line of their own.

* **Why.** Once the double-counted short straws were gone, 28 of the baseline's 34 distinct problems with an easy fix
  were liked-partner complaints, and in every one, the fix *raised* the likes penalty as well as the others. The likes
  penalty rewards how much liked pairing there is in total, not how evenly it's spread, so no parameter setting can
  remove them; only a change to the formula could. It also isn't clear that workers hold "they got their friends
  more often than I got mine" against a schedule the way they hold load or short straws against it.
* **The alternative not taken:** a fairness term in the likes penalty, each worker's shortfall of liked pairings
  through a convex function, as workload does ([Future work](future-work.md#a-fairness-term-for-liked-pairings)).
* **Signs this was the wrong choice:** workers complaining about who got paired with their friends; schedules whose
  liked-partner severity (shown by `tools/tune.py report`) grows as settings get better on the main measures; or
  cards read by hand where the liked-partner complaints look like the ones that matter most.

## Sampling

To compare the audit with the internal penalty, the sampler makes many legal schedules for one input by shuffling the
workers' order before the search, then audits and scores each. It reports:

* the **rank correlation** (Spearman) between the internal penalty and the severity with an easy fix, and between
  the penalty and the total severity;
* **disagreements**: the schedules among the best by internal penalty that have the most severity with an easy fix,
  with their summaries.

These are first legal schedules (the sampler doesn't use [branch and bound](search-algorithm.md#branch-and-bound-the-pocket),
which would give the same best schedule every time), not a random sample of all legal ones, which is enough to find
blind spots.

## Parameters

Named constants at the top of the audit's code: `TOLERANCE` (1), `DAY_BOUNDARY` (00:00), `SHORT_REST_MARGIN`
(2 hours), `MAX_CHANGES` (3). They're the audit's own, and unrelated to the [scoring parameters](scoring.md#parameters).
