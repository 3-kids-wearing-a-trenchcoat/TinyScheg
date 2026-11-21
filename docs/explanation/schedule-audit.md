# Schedule audit

The schedule audit is a **development tool**. It judges a finished schedule the way its workers would, to check that
the [scoring](scoring.md) and its [tuning](tuning.md) don't produce schedules that workers would rightly hold against
them. It isn't part of TinyScheg's regular operation.

> [!NOTE]
> **Implemented** in `tools/audit.py` and tested, as decided on 2026-11-19
> ([ADR 0048](../decisions/0048-an-audit-that-only-observes.md) and [ADR 0049](../decisions/0049-partners-in-the-audit.md))
> and amended on 2026-11-20 ([ADR 0050](../decisions/0050-a-fix-harms-only-where-a-workers-own-situation-gets-worse.md),
> and [ADR 0051](../decisions/0051-the-audit-after-reading-cards-by-hand.md) after reading cards by hand) and on
> 2026-11-21 ([ADR 0053](../decisions/0053-load-against-the-workers-own-share.md), load against the worker's own share,
> and [ADR 0054](../decisions/0054-rest-against-the-typical-rest.md), rest against the typical rest, after the
> [worker panel](../decisions/0052-a-worker-panel-as-a-check-on-the-audit.md) checked the audit);
> `tools/tune.py` ([reading the audit](tuning.md#reading-the-audit)) and `tools/audit_sample.py` ([sampling](#sampling))
> read it. Built in [Phase 13](../roadmap.md#phase-13-a-reliable-audit), step 3, and validated in its step 4.
> [Auditing a schedule](../how-to/audit-a-schedule.md) still describes the old report, until Phase 13's step 5.

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

* **Each grievance is an event the worker can point to:** a shift of theirs worked above their share, a rest shorter
  than someone else's, a shift with someone they dislike. There's no tolerance. In a 2-2-3 split, the worker with 3
  has a grievance, though someone had to do the third shift; whether it could have gone elsewhere is a fact the
  [easy fixes](#easy-fixes) report.
* **Unfairness against themselves, and the strongest case they can.** Each worker points to every way they were
  treated unfairly, never to a way they were better off. For load, that's work above their own share: a worker at
  their share carries no one else's work, however little someone else did. Rest has no share, so each rest is
  measured against what's typical in the schedule: the median rest, per hour of the shift before it. No kind uses
  a peer: disliked partners and missing likes are about the worker's own shifts.
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

Load is judged **against the worker's own share** ([ADR 0053](../decisions/0053-load-against-the-workers-own-share.md)),
in proportion to availability, the project's workload policy
([ADR 0013](../decisions/0013-availability-weighted-workload.md)). It's measured **in hours alone**
([ADR 0051](../decisions/0051-the-audit-after-reading-cards-by-hand.md)): two 2-hour shifts against one 4-hour shift
are as much load.

* **The share** is the schedule's hours split in proportion to availability: everyone's hours, times the worker's
  availability over everyone's. No peer is involved. A worker at their share has no load grievance, however little
  someone else did.
* **The extra hours above the share are counted in the worker's own shifts, shortest first, rounded to the nearest
  shift.** Each shift counts when at least half of it falls within what's left of the extra hours, so each event is a
  shift the worker can point to. One 6-hour shift against a share of 3 hours is 1 event; 4 hours in 2-hour shifts
  against a share of 3.6 is none; 5 extra hours in 2-hour shifts are 3 events.
* **The extra hours are the grievance's size,** a fact on it.

There's no separate comparison within a day. Work concentrated in time shows as [rest](#rest) events, since a rest is
judged by the shift before it.

**Still missed:** a worker available longer, against one available much less who did proportionally less. A peer's
load is never scaled up, so that pair isn't compared.

### Rest

* **A rest** is the time between two of a worker's consecutive shifts, counting only the part when they were
  available, as in the scoring ([ADR 0038](../decisions/0038-rests-count-only-available-time.md)).
  * Unavailability is neither work nor rest. The time between two periods of a [history](#with-a-history) counts as
    unavailable for everyone.
  * The legal minimum rest stays on the clock: it's a rule of what's legal, not something the audit judges.
  * The rests before a worker's first shift and after their last aren't judged.
* **A rest is judged by the shift just done,** as rest per hour of the shift before it
  ([ADR 0051](../decisions/0051-the-audit-after-reading-cards-by-hand.md)): a rest after a shift twice as long has to
  be twice as long to be as good. With shifts of equal length, it's just the rest. 6 hours after a 12-hour shift is
  shorter than 6 hours after a 2-hour one, and 10 hours after a 2-hour shift is longer than 8 hours after a 2-hour
  one, whatever shift follows. (The scoring's rest target uses the mean of the two shifts around a rest,
  [ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md).)
* **Compared with the schedule's typical rest** ([ADR 0054](../decisions/0054-rest-against-the-typical-rest.md)).
  * The typical rest is the median of every worker's rests in the schedule, each per hour of the shift before it.
  * Each rest shorter than the typical rest, per hour of the shift before it, is an event.
  * How much shorter is a fact on it, in hours: how much longer it would have to be to reach the typical rest, after
    a shift this long.
  * No peer is involved, and every shift length is held to the same rate. A worker on longer shifts who gets less rest
    per hour of work than the rest of the schedule has events, even where the schedule could have done no better.
    Whether it could have is what the [easy fixes](#easy-fixes) show.

The same rests for everyone give no event, however long or short they are. If most rests are 6 hours after 2-hour
shifts, a 6-hour rest after a 2-hour shift is no event.

### Disliked partners

A worker's **partners** are the workers in the other slots of the same shift, as in the scoring. **Each disliked
person in a shift is an event in itself,** with no peer, since the aim is no disliked pairing at all
([ADR 0049](../decisions/0049-partners-in-the-audit.md)):
* X and Y in one shift are two events.
* 5 shifts with X are five.
* The size of the crew doesn't dilute it.
* Each worker's own list counts. If A dislikes X but X doesn't dislike A, only A has the event.

### Missing likes

**Each of a worker's shifts with partners, none of whom they like, is an event,** with no peer
([ADR 0051](../decisions/0051-the-audit-after-reading-cards-by-hand.md)). Workers complain about not being with
someone they like, not about someone they like being with someone else.

* **A shift worked alone isn't an event:** there's nobody the worker could have been with.
* **A dislike cancels the like it meets.** If B dislikes A, A's like for B doesn't count, neither for A's missing
  likes nor for A's liked pairings, since pairing them costs more than it gains
  ([ADR 0023](../decisions/0023-dislikes-outweigh-likes.md)). B's disliked-partner events stay.
* A worker who likes nobody (once such likes are left out) has no missing likes.

The worker whose friends are rarely on duty has the most events, whatever the schedule. That's expected: tuning
compares settings on the same inputs, where what an input forces is the same on both sides, and the events with a
harmless fix pick out the ones that could have been avoided.

Each worker's **liked pairings** (their boon: each liked person in each of their shifts) are a fact on their card,
not a grievance. Tuning reads them as a total, and worker by worker.

## Easy fixes

An **easy fix** is a **nearby schedule** in which the grievance is gone: the audited schedule with a few changes.

* **The changes** are moves (a slot given to another worker) and swaps (two workers exchanging slots in different
  shifts). They're made in the new period only, since the history is what happened. A grievance about the history
  that has a fix is one the new period could have made up for.
* **The nearby schedule must be legal.** The changes only describe how it differs from the audited one, so their
  order doesn't matter, and only the end has to be legal. Every slot is always given to a worker with its role and
  available then, but a change may leave a worker holding two slots too close together (closer than the minimum
  rest, or overlapping) if the next change resolves it. That way two workers can trade their shifts when either swap
  alone would leave one of them with shifts too close together. A conflict that only two later changes could
  resolve isn't searched. Tests check the search against brute force (every legal schedule within K changes) on
  small inputs.
* **The fix's size** is its number of changes, a fact on it.

**Only the nearby schedule is judged,** never each step on the way. It's audited afresh by the same rules, with its
own typical rest, and compared with the audited schedule worker by worker and kind by kind, never across kinds:

1. **The grievance is gone.** The worker has fewer events of that kind (with that person, for partners).
2. **The worker is better off** in that kind's own terms: worse in none of its facts, and better in at least one.
   * Load: fewer hours.
   * Rest: the new rests, compared with the old as with a peer's, none shorter and at least one longer.
   * Disliked partner: one shift fewer with that person.
   * Missing likes: fewer shifts with nobody they like.

   So making the peer worse off is no fix. If A's shortest rest is 6 hours and B's is 8, cutting B's to 6 removes
   A's event, but A gained nothing.
3. **Harmless or a transfer** ([ADR 0050](../decisions/0050-a-fix-harms-only-where-a-workers-own-situation-gets-worse.md)).
   A worker, the aggrieved one included in other kinds, is **harmed** where, in one kind, they have more events (or
   a rest event larger when sorted by size) **and** their own situation in that kind got worse:
   * load: more hours;
   * rest: more rests than before, or a rest shorter than the one in its place before;
   * disliked partner: more shifts with that person;
   * missing likes: more shifts with nobody they like.

   A grievance that grows only because someone else is better off isn't harm: after Jeff gives away a shift and rests
   longer, the typical rest may rise, and others' rests fall further short of it, though nothing in their own
   schedules changed. The fix is **harmless** if it harms nobody; otherwise it's a **transfer**, reported with exactly
   what it creates and for whom. In a 3-2-1 split, giving one of the first worker's shifts to the third (2-2-2) harms
   nobody; giving it to the second (2-3-1) gives them a load event.
   * With no tolerance, most load fixes are transfers: the extra shift in a 2-2-3 split can only move.
   * A fix is dropped when another creates a subset of what it creates, with no more changes. A harmless fix creates
     nothing, so it drops every transfer of its size or larger.

**The search is complete up to K changes,** smallest fix first. K is a command-line option, 3 by default.
* Each nearby schedule is audited once and checked against every grievance, so nothing is skipped.
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

* **How far the fix search reached** comes first: "fixes searched up to 3 changes", or "fix search off" with
  `--max-changes 0`. With a history, a line about it comes before that.
* **A card per worker** comes next. It shows their facts:
  * shifts and hours;
  * availability (while a post is staffed), out of the hours when any post is;
  * their rests, in time order;
  * their partners, with counts;
  * their liked pairings.

  Then each grievance:
  * what it points to: the extra hours; each rest, with the shifts around it and who else was in them, so that a
    short rest into a shift with a friend can be seen; each shift with a disliked person; each shift with nobody they
    like, with who was in it;
  * the peer it's measured against (for load and rest), with both sides' facts in natural units;
  * its size, where it has one: the extra hours, each rest's hours short;
  * its smallest harmless fix (with how many changes it takes and how many events it removes), or else its
    transfers, fewest changes first, each with what it creates, or else "no fix of up to K changes". A grievance whose
    events are all wholly in the history (rests between two history shifts, history shifts with a disliked person or
    with nobody they like) says that no change can reach it instead; an event of that kind among others is marked "(in the history)".

  For example, from a first legal schedule of the example (seed 7 of the sampler, transfers cut short here):

  ```
  Jill: 2 shifts, 7 h; available 24 h (of 24 h with a post staffed)
    rests: 7 h
    partners: Ninsun ×1; liked pairings: 0
    grievances:
      - load: 1.62 h more than Jill's share of 5.38 h (the schedule's hours in proportion to availability), as much
        as 1 shift of Jill's (7 h in 2 shifts)
        harmless fix (2 changes, removes 1 event): give Enkidu Anne's front gate 2025-01-01 10:00–13:00; give Anne
          Jill's front gate 2025-01-01 19:00–22:00
      - rest: 1 rest shorter than the typical rest of 2.33 h per hour of the shift before it
          7 h, between desk 2025-01-01 08:00–12:00 and front gate 2025-01-01 19:00–22:00 (with Ninsun): 2.33 h
            short, after a 4 h shift (1.75 h per hour of it), of the typical 9.33 h after a shift this long
        transfers, each removing events but creating others:
          2 changes, removes 1 event: give Anne Jill's front gate 2025-01-01 19:00–22:00; give Jill Shamhat's front
            gate 2025-01-01 22:00–2025-01-02 00:00 -> Jeff: 1 more shift with Jill, whom they dislike; Anne: 1 more
            load event, 2 more rests shorter than the typical rest
      - missing like: 1 shift with nobody they like (they like Jack)
          front gate 2025-01-01 19:00–22:00 (with Ninsun)
        harmless fix (2 changes, removes 1 event): give Enkidu Anne's front gate 2025-01-01 10:00–13:00; give Anne
          Jill's front gate 2025-01-01 19:00–22:00
  ```

  All transfers are shown, one per line (on 50 samples of the example, a median of 6 per grievance with only
  transfers, at most 12; on the tuning schedules, 17, at most 93). Reading cards by hand (2026-11-20), the user kept
  them all rather than choose which to leave out: the grievances matter more, and come first.
* **A closing table** of counts, per worker and per kind. Each cell gives the events, then, in brackets, how many of
  them belong to a grievance with a harmless fix, with only transfers, or with no fix within K, and how many lie
  wholly in the history. A grievance's events are counted under its fix, which may remove only some of them (its card
  says how many).

  ```
  events by kind (with a harmless fix / only transfers / no fix of up to 3 changes / in the history)
             load         rest         disliked partner  missing like
  Jack       0            1 (0/1/0/0)  0                 0
  Jill       1 (1/0/0/0)  1 (0/1/0/0)  0                 1 (1/0/0/0)
  Jeff       0            0            0                 0
  ```

  * Workers are listed in input order, since ranking them would take a rule across kinds.
  * Nothing is added across kinds.

With `--json`, the audit prints the same content as JSON instead, for tools: the reach (`max_changes`), and for each
worker their facts, their grievances (each with its events, its harmless fix or transfers, with every change and what
it creates) and their counts per kind. [`tools/tune.py`](tuning.md) records the following from it, for each run and
per kind:
* the events;
* the most aggrieved worker's events;
* the events with a harmless fix;
* for load and rest, the same three in hours: extra hours, hours short.

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

To compare the audit with the internal penalty, the sampler (`tools/audit_sample.py`) makes many legal schedules for
one input by shuffling the workers' order before the search, then audits and scores each. It lists each schedule,
best penalty first, with each kind's events and how many have a harmless fix, and reports, per kind (kinds are never
added together):

* the **rank correlation** (Spearman) between the internal penalty and the number of events, and between the
  penalty and the events with a harmless fix; for load and rest, in hours too (extra hours, hours short);
* **disagreements**: the schedules among the best quarter by internal penalty that still have events of that kind
  with a harmless fix, up to three, the best by penalty first. A harmless fix in the penalty's favourite schedule is a
  direct sign the penalty missed something.

Its fix search reaches K changes like the audit's (`--max-changes`, 3 by default).

These are first legal schedules (the sampler doesn't use
[branch and bound](search-algorithm.md#branch-and-bound-the-pocket), which would give the same best schedule every
time), not a random sample of all legal ones, which is enough to find blind spots.

## Parameters

Only how far "no fix" reaches: K, 3 by default (a named constant), set with a command-line option, and recorded with
every result. Besides that, only how many decimals numbers are shown with. There's no tolerance, margin or weight:
every rule is a sentence about how workers judge.

## The audit until Phase 13

> [!NOTE]
> **Replaced**, and its code removed, in [Phase 13](../roadmap.md#phase-13-a-reliable-audit)'s step 3
> (2026-11-20). The full description is in this page's history (before 2026-11-19), its code in the repository's
> history (before 2026-11-20), and what's wrong with it in [ADR 0048](../decisions/0048-an-audit-that-only-observes.md).
> The tuning results measured with it are kept as history ([tuning](tuning.md)).

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
