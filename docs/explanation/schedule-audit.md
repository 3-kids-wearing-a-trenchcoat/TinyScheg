# Schedule audit

The schedule audit is a **development tool**. It judges a finished schedule the way its workers would, to check that
the [scoring](scoring.md) and its [tuning](tuning.md) don't produce schedules that workers would rightly hold against
them. It isn't part of TinyScheg's regular operation.

> [!IMPORTANT]
> **Partially implemented.** Decided on 2026-11-19
> ([ADR 0048](../decisions/0048-an-audit-that-only-observes.md) and [ADR 0049](../decisions/0049-partners-in-the-audit.md)),
> and being built in [Phase 13](../roadmap.md#phase-13-a-reliable-audit), step 3. The [grievances](#grievances) and
> the [easy fixes](#easy-fixes) are in `tools/audit.py` (`find_grievances`, `search_fixes`) and tested; [the
> report](#the-report) and the tools reading it aren't yet. Until they are, `tools/audit.py` and `tools/audit_sample.py` do what's described
> under [the audit until Phase 13](#the-audit-until-phase-13). See [Auditing a schedule](../how-to/audit-a-schedule.md)
> for how to run them.

## Why a separate audit

The internal penalty has to be cheap, monotone along the search and measured in fixed units, so it's a compressed
summary of fairness. The audit has none of those constraints: it can be slow and detailed, and it describes each
worker's experience in the terms workers actually use. Comparing the two shows where the summary misses something.

To keep the comparison meaningful, the audit is **independent**. To read the input and list the shifts, it uses
`tinyscheg.model`, `tinyscheg.parsing` and `tinyscheg.timing`. It reads the assignment from the written schedule file
([`tinyscheg.parsing.schedule_reader`](../reference/api/parsing.md#schedule_reader-module), in any of the output
formats). For legality, it uses the independent hard-constraint checker
([`tools/schedule_checker.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/tools/schedule_checker.py)),
which also checks the minimum rest after each worker's history shifts. It has its own legality check for fixes and
uses nothing from `csp/` or `scoring/`, so a bug or blind spot there can't hide the same one here, and the model never
grades itself.

## The audit only observes

The audit lists, for each worker, the **grievances** they can point to, with their facts and the fixes found for
them. Nothing in it has a number or value to tune:
* no scores or severities;
* no summary verdict;
* no "unavoidable" label;
* no kind of grievance set apart or weighed against another.

What matters more is decided where the results are read, in [tuning](tuning.md):
* one kind of grievance against another;
* evenness against the total;
* which grievances could have been avoided.

That way, a surprising result can be traced either to the audit describing the schedule wrongly or to how it was
read.

## How workers judge a schedule

The audit models workers who are **sensitive to being treated unfairly**:

* **Each grievance is an event the worker can point to:** an extra shift, a rest shorter than someone else's, a shift
  with someone they dislike. There's no tolerance. In a 2-2-3 split, the worker with 3 has a grievance, though
  someone had to do the third shift; whether it could have gone elsewhere is a fact the [easy fixes](#easy-fixes)
  report.
* **Worse off only, and the strongest case they can.** Each worker points to every way they were worse off than a
  peer, never to a way they were better off. Each measures themselves against the peer who makes their case best:
  the **best-off peer**, the one giving the most events.
* **No netting.** A boon (a shift with a friend) is never set against a straw (a short rest), by the workers or by the
  audit.
* **Lines are drawn from the schedule itself.** No line is set by hand, so if everyone does the same work and rests
  the same, it's fair however long either is.
* **Fairness only.** The audit doesn't measure how good the schedule is otherwise. Everyone resting less, but
  equally, is no grievance (levelling down). Tuning reads the audit together with measures that don't come from it.

Every shift counts the same, whatever the time of day. Like the scoring, the audit makes no distinction between day
and night shifts.

## Grievances

There are four kinds: [load](#load), [rest](#rest), [disliked partners](#disliked-partners) and
[missing likes](#missing-likes). Each is judged over the whole schedule, with its [history](#with-a-history) if it has
one. Roles are ignored when finding grievances: availability defines what a worker owes, and roles only limit what
they can do ("a role isn't a punishment"). Whether anything could have been done is what the easy fixes show.

**Availability** is counted only in the hours when at least one post is staffed. Being unavailable when there was
nothing to do costs nothing, so it doesn't lower what a worker owes.

### Load

Load is judged **in proportion to availability**, the project's workload policy
([ADR 0013](../decisions/0013-availability-weighted-workload.md)). It's measured in **shifts** and in **hours**,
with no exchange rate between the two.

* **Peers.** A worker is compared only with peers available at least as long, and for some time at all.
* **Scaled down, never up.** The peer's shifts and hours are scaled to the worker's availability. A peer available
  48 hours who did 4 shifts counts, for a worker available 40 hours, as 3⅓. Scaling up a barely available peer's load
  would turn a fraction of a shift into whole grievances.
* **More only by one measure and no less by the other.** More shifts but fewer hours than the scaled peer, or the
  reverse, isn't more load.
* **Each whole extra shift is an event.** Fractions don't count, so 5 shifts against 3⅓ is 1 event.
* **An excess in hours is counted in the worker's own shifts, shortest first.** It's as many events as the shortest
  shifts that fit in it. 5 hours more, with shifts of 3 hours, is 1 event, so each event is a shift the worker can
  point to.
* **Where both measures show more, the larger count** is taken. The best-off peer is the one giving the most events.

There's no separate comparison within a day. Work concentrated in time shows as [rest](#rest) events, since a rest is
judged with the shifts around it.

**Still missed:** a worker available longer, against one available much less who did proportionally less. A peer's
load is never scaled up, so that pair isn't compared.

### Rest

* **A rest** is the time between two of a worker's consecutive shifts, counting only the part when they were
  available, as in the scoring ([ADR 0038](../decisions/0038-rests-count-only-available-time.md)).
  * Unavailability is neither work nor rest. The time between two periods of a [history](#with-a-history) counts as
    unavailable for everyone.
  * The legal minimum rest stays on the clock: it's a rule of what's legal, not something the audit judges.
  * The rests before a worker's first shift and after their last aren't judged.
* **A rest is judged with the shifts around it,** as rest per hour of the two shifts: the rest divided by
  $(|s| + |s'|) / 2$, the shape of the scoring's rest target
  ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)). With shifts of equal length, it's
  just the rest. 6 hours between a 12-hour and a 2-hour shift is shorter than 6 hours between two 2-hour shifts.
* **Compared rest by rest, against the best-off peer.**
  * Each worker's rests are sorted shortest first and compared with the peer's in the same places, up to the smaller
    number of rests.
  * Each place where the worker's rest is shorter is an event.
  * How much shorter is a fact on it, in hours: how much longer it would have to be to match the peer's, for shifts
    this long.
* **Every worker is a peer.** Rests aren't scaled, since they're already measured in available time and per hour of
  work.

The same rests for everyone give no event, however long they are. Pairing the rests in any other order than shortest
with shortest would give events even then.

### Disliked partners

A worker's **partners** are the workers in the other slots of the same shift, as in the scoring. **Each disliked
person in a shift is an event in itself,** with no peer, since the aim is no disliked pairing at all
([ADR 0049](../decisions/0049-partners-in-the-audit.md)):
* X and Y in one shift are two events.
* 5 shifts with X are five.
* The size of the crew doesn't dilute it.
* Each worker's own list counts. If A dislikes X but X doesn't dislike A, only A has the event.

### Missing likes

A missing like is a grievance only against a peer. It's judged by the worker's **own** likes applied to the peer's
shifts: "your shifts would have put me with someone I like more often than mine did".

* **Counting.** For each person the worker likes, count the peer's shifts with that person in them (apart from the
  worker and the peer), and the worker's own shifts with them.
* **Scaling.** If the peer did more shifts, their count is scaled down to the worker's number of shifts, never up.
* **Events.** Each whole pairing more is an event, one of the peer's shifts the worker can point to.
* **Peers.** Every worker can be the peer, and the best-off peer is the one giving the most events. A worker who
  likes nobody has no such grievance.

Each worker's **liked pairings** (their boon) are a fact on their card, not a grievance. Tuning reads them as a
total, and worker by worker.

This is the **least settled** of the audit's decisions. The alternative kept for a revisit is no like grievance at
all, only the boon count ([ADR 0049](../decisions/0049-partners-in-the-audit.md)).

## Easy fixes

An **easy fix** is a **nearby schedule** in which the grievance is gone: the audited schedule with a few changes.

* **The changes** are moves (a slot given to another worker) and swaps (two workers exchanging slots in different
  shifts). They're made in the new period only, since the history is what happened. A grievance about the history
  that has a fix is one the new period could have made up for.
* **The nearby schedule must be legal.** The changes only describe how it differs from the audited one, so their
  order doesn't matter. The search reaches it one legal change at a time, in every order, and tests check on small
  inputs that this misses nothing.
* **The fix's size** is its number of changes, a fact on it.

**Only the nearby schedule is judged,** never each step on the way. It's audited afresh by the same rules, with its
own best-off peers, and compared with the audited schedule worker by worker and kind by kind, never across kinds:

1. **The grievance is gone.** The worker has fewer events of that kind (with that person, for partners).
2. **The worker is better off** in that kind's own terms: worse in none of its facts, and better in at least one.
   * Load: no more shifts and no more hours, and fewer of one.
   * Rest: the new rests, compared with the old as with a peer's, none shorter and at least one longer.
   * Disliked partner: one shift fewer with that person.
   * Missing like: one more with them.

   So making the peer worse off is no fix. If A's shortest rest is 6 hours and B's is 8, cutting B's to 6 removes
   A's event, but A gained nothing.
3. **Harmless or a transfer.** The fix is **harmless** if no worker, the aggrieved one included in other kinds, has
   more events of any kind, or a rest event larger when sorted by size. Otherwise it's a **transfer**, reported with
   exactly what it creates and for whom.
   * With no tolerance, most load fixes are transfers: the extra shift in a 2-2-3 split can only move.
   * A fix is dropped when another creates a subset of what it creates, with no more changes. A harmless fix creates
     nothing, so it drops every transfer of its size or larger.

**The search is complete up to K changes,** smallest fix first. K is a command-line option, 3 by default.
* Its only shortcut can't lose a fix: at least one change must touch the grievance's workers.
* So "no fix" is an exact claim, always stated with its K: "no fix of up to 3 changes". K sets how far the claim
  reaches, not what a grievance is.
* K = 0 turns the search off, with no claim about fixes either way.
* Each change more multiplies the time by about the number of legal changes: about 30 on 24-hour schedules, 90 on
  48-hour ones. Up to 3 changes takes seconds on the example and up to about 5 minutes on a 48-hour schedule.

A lab check on 2026-11-19, with the earlier grievance definitions, showed what a complete search finds that greedy
chains miss. On 200 samples of the example, every complaint the greedy chains left without a fix had one of 2 or 3
changes. Requiring each step to be harmless had blocked them: in some samples, almost nothing is reachable that way
([ADR 0048](../decisions/0048-an-audit-that-only-observes.md)).

## The report

* **K** comes first.
* **A card per worker** comes next. It shows their facts:
  * shifts and hours;
  * availability (while a post is staffed);
  * their rests;
  * their partners, with counts;
  * their liked pairings.

  Then each grievance:
  * what it points to;
  * the peer it's measured against, with both sides' facts in natural units;
  * its size, where it has one;
  * its smallest harmless fix, or its transfers, or "no fix of up to K changes". An event wholly in the history (a
    rest between two history shifts, a disliked partner in a history shift) says so instead, since no change can
    reach it.

  A rest event shows the shifts around it and who was in them, so that a short rest into a shift with a friend can be
  seen. For example:

  ```
  Dana: 5 shifts, 15 h; available 40 h (of 48 h with a post staffed)
    rests: 4 h, 6 h, 10 h, 12 h
    partners: Eli ×2, Gil ×1, Ivo ×1; liked pairings: 2
    grievances:
      load: 1 extra shift (5 shifts, 15 h; Finn's 4, 12 h, scaled to Dana's availability: 3.33, 10 h)
        transfers (1 change): give Gil Dana's Tue 13:00-16:00 -> creates Gil: 1 extra shift
                              give Hana Dana's Tue 13:00-16:00 -> creates Hana: 1 extra shift
      rest: 4 h, Tue 16:00-20:00, between Tue 13:00-16:00 (with Eli) and Tue 20:00-23:00 (with Gil);
            2 h shorter than Finn's shortest rest, for shifts this long
        fix (2 changes): give Gil Dana's Tue 20:00-23:00; give Dana Gil's Wed 08:00-11:00
      disliked partner: Wed 14:00-17:00, with Ivo
        no fix of up to 3 changes
  ```

  All transfers are shown, one per line, until reading cards shows that's too long.
* **A closing table** of counts, per worker and per kind. Each cell gives the events, and how many of them have a
  harmless fix, how many only transfers, how many no fix within K, and how many lie wholly in the history.
  * Workers are listed in input order, since ranking them would take a rule across kinds.
  * Nothing is added across kinds.

With `--json`, the audit prints the same content as JSON instead, for tools.
[`tools/tune.py`](tuning.md) records the following from it, for each run and per kind:
* the events;
* the most aggrieved worker's events;
* the events with a harmless fix.

It also records the liked-pairings total and K.

## With a history

A schedule with a [history](../reference/input-format.md#history) is audited **together with it, as one schedule**,
as the scoring sees it ([ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md)): workers judge
the new schedule by everything they've done. The audit builds the whole schedule itself, from the model alone,
independently of `tinyscheg.csp`:

* each previous schedule's shifts come from its own input, with its workers matched by name (slots of workers who
  have left are dropped), then the new period's;
* each worker's availability comes from each period's input. They have none during a period whose input they weren't
  in (they joined later), and nobody has any between periods;
* **easy fixes change only the new period.** An event wholly in the history says so on the card.

## Sampling

To compare the audit with the internal penalty, the sampler makes many legal schedules for one input by shuffling the
workers' order before the search, then audits and scores each. It reports, per kind:

* the **rank correlation** (Spearman) between the internal penalty and the number of events;
* **disagreements**: the schedules among the best by internal penalty that still have grievances with a harmless
  fix. A harmless fix in the penalty's favourite schedule is a direct sign the penalty missed something.

These are first legal schedules (the sampler doesn't use
[branch and bound](search-algorithm.md#branch-and-bound-the-pocket), which would give the same best schedule every
time), not a random sample of all legal ones, which is enough to find blind spots.

## Parameters

Only how far "no fix" reaches: K, 3 by default (a named constant), set with a command-line option, and recorded with
every result. Besides that, only how many decimals numbers are shown with. There's no tolerance, margin or weight:
every rule is a sentence about how workers judge.

## The audit until Phase 13

> [!NOTE]
> **Implemented** in `tools/audit.py` and `tools/audit_sample.py`, and covered by tests, until it's rebuilt in
> [Phase 13](../roadmap.md#phase-13-a-reliable-audit), step 3. The full description is in this page's history
> (before 2026-11-19), and what's wrong with it in [ADR 0048](../decisions/0048-an-audit-that-only-observes.md).

* **Complaints, per pair.** Each complaint was by one worker against one peer (a peer available at least as long),
  past a **tolerance** of one. Its **severity** was how far past the tolerance it went.
* **Load** was compared over the whole schedule and in any 24 hours, with an excess in hours divided by the worker's
  shortest shift.
* **Short straws** were counted and compared: a rest more than 2 hours below the schedule's median rest, and a shift
  with anyone disliked, added together one for one.
* **Liked pairings** were compared between workers who like anyone, each by their own list.
* **Easy fixes** were greedy chains of at most 3 moves and swaps, each one harmless and narrowing the complaint.
* **The group summary** gave the severity with and without an easy fix, and the share of all severity held by the
  most aggrieved worker. Tuning ranked settings by these.

### Liked-partner complaints are counted apart

Decided on 2026-11-11, and replaced by [ADR 0049](../decisions/0049-partners-in-the-audit.md):
* The cards listed liked-partner complaints with their easy fixes, but the summary's main measures (and so tuning's
  priorities) left them out.
* The likes penalty rewards how much liked pairing there is in total, not how evenly it's spread, so no parameter
  setting could remove them.
* It wasn't clear workers hold "they got their friends more often than I got mine" against a schedule.
