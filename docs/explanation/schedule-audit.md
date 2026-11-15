# Schedule audit

The schedule audit is a **development tool**: it judges a finished schedule the way its workers would, to check that
the [scoring](scoring.md) and its tuning don't produce schedules that workers would rightly complain about, such as
unfairness concentrated on a few workers. It isn't part of TinyScheg's regular operation.

> [!NOTE]
> **Implemented** in `tools/audit.py` and `tools/audit_sample.py`, and covered by tests. See
> [Auditing a schedule](../how-to/audit-a-schedule.md) for how to run it.

## Why a separate audit

The internal penalty has to be cheap, monotone along the search and measured in fixed units, so it's a compressed
summary of fairness. The audit has none of those constraints: it can be slow and detailed, and it describes each
worker's experience in the terms workers actually use. Comparing the two shows where the summary misses something.

To keep the comparison meaningful, the audit is **independent**: it uses `tinyscheg.model` and `tinyscheg.parsing`
to read the input and list the shifts, the written schedule file for the assignment
([`tinyscheg.parsing.schedule_reader`](../reference/api/parsing.md#schedule_reader-module), in any of the output formats),
and the independent hard-constraint checker, which also checks the minimum rest after each worker's history shifts
([`tools/schedule_checker.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/tools/schedule_checker.py))
for legality — and nothing from `csp/` or `scoring/`. A bug or blind spot there can't hide the same one here.

## How workers judge a schedule

The audit is built on how workers actually react to a schedule. It models **self-centred, jealous workers**, whose
two questions are "why is he getting more than me?" and "why wasn't my request met, when it easily could have been by
doing X?":

* **Relative, not absolute.** Workers compare themselves with each other: not "why do I have three shifts today?"
  but "why am I doing three shifts today when X only does two?".
* **Each schedule sets its own norms.** What's good or bad is judged against what the schedule usually gives, not
  against an absolute standard. If a schedule usually gives 12 hours of rest, a worker with two 8-hour rests drew
  short straws, though 8 hours is generous in itself; if everyone rests 6 hours, a 6-hour rest is just the norm.
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

Load is compared over the **whole period** and **in any day**: each worker wants to do no more than anyone else,
both during the day and in the schedule overall.

* **A day is any 24 hours** (`DAY_LENGTH`) within the period, wherever it starts. Midnight means nothing special, as
  the schedule makes no distinction between day and night: two shifts two hours apart are on the same day even if
  midnight falls between them. A shift counts in **every day it overlaps**, with the hours of it that fall in that
  day: a 14:00–20:00 shift counts in the day from 17:00, with 3 hours.
* In practice, the windows compared start at each shift's start, end at each shift's end, and start and end at the
  period's ends; whatever shifts overlap some 24 hours also overlap one of those.
* A worker complains about a peer **once** for the day, over the window where the gap is widest, so overlapping
  windows don't count the same extra load several times. Peers are found per window, as usual.
* A period of 24 hours or less has no separate day comparison: the whole period is the day.
* Load is measured both in **shifts** and in **hours**, with **no exchange rate** between the two: A did more than B
  only if A did more by one measure and **no less by the other**. More shifts but fewer hours, or the reverse, isn't
  more load, and there's no complaint either way.
* The gap is then the larger of the difference in shifts and the difference in hours divided by **A's own shortest
  shift** in the window, with the same tolerance of one. Moving a shift of h hours from A to B turns a gap of g hours
  into g − 2h, which is narrower only if h is less than g: so a gap in hours no larger than A's shortest shift can't
  be narrowed by moving one of A's shifts, just as a gap of one shift can't. With equal shift lengths, the two
  measures agree.

For example, if A did 4 shifts of 4 hours within some 24 hours and B, available all that time, did 2, the gap is 2
and A has a complaint of severity 1 against B. If A did two 6-hour shifts and B a 6-hour and a 2-hour shift (12
hours against 8, as many shifts), the gap of 4 hours is less than A's shortest shift: tolerated, since giving B
either of A's shifts would leave them further apart. If instead A did a 2-hour and a 12-hour shift and B two 4-hour
shifts (14 hours against 8), the gap is 6 / 2 = 3, severity 2: A's 2-hour shift could have gone to B.

(Decided 2026-11-13, with the user aspiring not to decide how much an extra shift is worth. It used to be the larger
of the difference in shifts and the difference in hours over the window's longest shift: an exchange rate, which in
the day-2 checks let a fix give a worker who did fewer but longer shifts another one and leave them 4-6 hours above
everyone, as "within the tolerance". Counting a shift only in the days it started in let a 6-hour shift that began
3 hours before a window count for nothing in it.)

(Decided 2026-11-12. Days used to be calendar days, from midnight, with a shift belonging to the day it starts on.
In the tuning checks, almost every per-day complaint came from that split alone: in a schedule starting at 16:00,
a worker with shifts at 01:00 and 12:00 complained about one who worked 20:00–00:00, though their loads over the
schedule were within the tolerance, and a 22:00–04:00 shift counted for nothing on the day most of its hours fell
on.)

### Short straws

A **short straw** is a bad draw. Each worker's short straws over the whole period are counted, and compared between
peers (available at least as long over the whole period) with the same tolerance:

* **Short rest** — a rest between two of the worker's shifts that's more than `SHORT_REST_MARGIN` (2 hours) shorter
  than the schedule's **typical rest**: the median of all the rests between shifts in the schedule, everyone's
  together. (Decided 2026-11-12; it used to be any rest under `min_rest + SHORT_REST_MARGIN`, close to the legal
  minimum, but in the tuning benchmarks most rests were that short, so it counted the norm as a straw.)
  The norm is the **audited schedule's**: [easy fixes](#easy-fixes) are judged against it, not against a norm of
  their own. (Decided 2026-11-13: otherwise a fix that shortens rests lowers the median, and with it the threshold,
  so that short rests stop counting; in a day-2 check, a fix cut the most crammed worker's rest from 10 hours to 6
  and the audit counted fewer short straws.)
* **Disliked partner** — each shift shared with a worker they dislike.

Having the most shifts in a day isn't a short straw: [load](#load) already compares load in any day, with the same
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
Harmless means: compared with the audited schedule, it creates no new complaint, makes no existing complaint more
severe, for anyone, and gives **nobody a short straw** of any kind they didn't have (a short rest by the audited
schedule's norm, or a disliked partner). Otherwise the fix only moves the problem around. A straw happens to a worker
whatever the others have, so it counts even when the worker stays within the tolerance and nobody would complain.
(Decided 2026-11-13: in a day-2 check, a fix gave a worker a new 6-hour rest, allowed because their count of straws
stayed within one of the others'.)

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

* A **card per worker**: their shifts and hours (overall, and in their busiest 24 hours) against their availability, their shortest
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

## With a history

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_audit.py`, `tests/test_history_input.py`).

A schedule with a [history](../reference/input-format.md#history) is audited **together with it, as one schedule**,
as the scoring sees it ([ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md)): workers judge
the new schedule by everything they've done, so load, short straws and pairings are compared over the history and
the new period together. The audit builds the whole schedule itself, from the model alone, independently of
`tinyscheg.csp`:

* each previous schedule's shifts, from its own input, with its workers matched by name (slots of workers who have
  left dropped), then the new period's;
* each worker's availability in each window from each period's input, none during a period whose input they weren't
  in (they joined later) and none between periods;
* **easy fixes may change only the new period**: the history is what happened. A complaint about the history with
  an easy fix is one the new schedule could have made up for and didn't.

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

Named constants at the top of the audit's code: `TOLERANCE` (1), `DAY_LENGTH` (24 hours), `SHORT_REST_MARGIN`
(2 hours), `MAX_CHANGES` (3). They're the audit's own, and unrelated to the [scoring parameters](scoring.md#parameters).
