# 0048. An audit that only observes: each worker's grievances as events, against the best-off peer

**Status:** Accepted (one sentence on how the fix search reaches a nearby schedule corrected on 2026-11-20, in
place); amended by [ADR 0050](0050-a-fix-harms-only-where-a-workers-own-situation-gets-worse.md) (which fixes are
harmless). Partners (disliked and liked workers in a shift) are decided apart, in
[ADR 0049](0049-partners-in-the-audit.md).

## Context

The [schedule audit](../explanation/schedule-audit.md) judges a finished schedule the way its workers would, and is
what the scoring is [tuned](../explanation/tuning.md) against. As built by 2026-11-19, it put values on what it found:

* **A tolerance of one:** a gap of one shift, short straw or pairing between two workers was no complaint, two was.
* **A short rest was a fixed margin** (2 hours) below the schedule's typical rest, the median of everyone's rests.
* **Short rests and disliked partners were added together, one for one,** as short straws.
* **Severities were summed** across kinds and across pairs of workers, so the totals grew with the number of peers.
  Tuning ranked settings by those sums: severity with an easy fix, then concentration, then the total.
* **Load was also compared in any 24 hours**, besides over the whole schedule.
* **Fixes were found greedily:** at most three changes, each one harmless and narrowing the complaint. "No easy fix
  found" said little.

The user (2026-11-19) worried that the audit only shifts the problem, since it still prices every miss. They want
it to "just produce a list of grievances for each worker", with nothing given an explicit number or value to tune,
"as close to accurate as possible", and to keep any inferences from it outside it, "so we don't doubt the audit
itself". If a tuning result is surprising, it should be possible to tell whether the audit described the schedule
wrongly or the reading of it was wrong.

The decisions below were taken with the user in seven groups (the roadmap's
[Phase 13](../roadmap.md#phase-13-a-reliable-audit), step 1, 2026-11-19), each discussed until both agreed, with two
lab checks. Where a question has no clear answer, the audit asserts only what holds under every reasonable answer.

## Decision

### 1. Grievances are events, against the best-off peer

1. **A grievance is an event the worker can point to:** an extra shift, a rest shorter than a peer's, a shift with
   someone they dislike. It isn't a comparison that counts only past a tolerance, which would build in "someone had
   to".
2. **Any line an event needs is drawn from the schedule itself,** never set by hand. So the same work and rest for
   everyone is fair however long they are.
3. **The audit measures fairness only**, not how good the schedule is otherwise. Everyone resting less, but equally,
   is no grievance. Tuning reads the audit together with measures that don't come from it. Among the tuning results
   so far, such levelling down appeared once, on one input (`sweep_10` as day 2), by an hour.
4. **Where an event is measured against peers, it's against the best-off peer,** the one giving the most events. It's
   never counted once per peer, which made the count grow with the number of peers.
5. **The workers are sensitive to being treated unfairly.** Each points to every way they were worse off than a peer,
   never to a way they were better off, and makes the strongest case they can. That's why the best-off peer counts.
   They never set a boon against a straw: the audit doesn't net.
6. **The horizon is the whole schedule,** with the history the input carries, as in the scoring
   ([ADR 0031](0031-history-as-the-filled-part-of-one-schedule.md)). Fixes change only the new period.

### 2. Load

1. **In proportion to availability,** the project's workload policy
   ([ADR 0013](0013-availability-weighted-workload.md)).
   * A worker is compared only with peers available at least as long (and for some time at all).
   * The peer's load is scaled down to the worker's availability, never up. Scaling up a barely available peer's load
     would turn a fraction of a shift into whole grievances.
2. **Availability counts only the hours when at least one post is staffed.** Being unavailable when there was nothing
   to do costs nothing, so it doesn't lower what a worker owes. It isn't weighted by how much work there was: that
   would be a different policy, which ADR 0013 doesn't adopt. To revisit if it turns out to matter.
3. **Roles are ignored when finding grievances.** Availability defines what a worker owes; roles only limit what
   they can do ("a role isn't a punishment"). The fix search shows when nothing could be done.
4. **Shifts and hours, with no exchange rate**
   ([ADR 0026](0026-workload-counts-shifts-and-hours.md)). A worker did more than a peer only if they did more by one
   measure and no less by the other.
5. **Each whole extra shift against the scaled peer is an event, with no tolerance.** In a 2-2-3 split, the worker
   with 3 has one.
   * An excess in hours is counted in the worker's own shifts, shortest first, so that each event is a shift they can
     point to. Dividing it by their shortest shift, as before, could count more events than they have shifts.
   * Where both measures show more, the larger count is taken.
6. **No 24-hour window.** A lab check on 62 stored tuning schedules longer than 24 hours (1,050 per-day complaints,
   counted per pair) sorted the per-day complaints:
   * 42% were by workers who also did more over the whole schedule.
   * 8% had a short rest in that day.
   * 31% came from doing more by one measure and less by the other over the whole schedule. Within a day the two
     measures line up, so the window was a back door to an exchange rate.
   * 19% were about where the work fell in time, with as much or less overall (as on `multiday_05`, judged not
     unfair).

   What's left, work concentrated in time that no short rest shows, is covered by judging a rest with the shifts
   around it (below).

**Still missed:** a worker available longer, against one available much less who did proportionally less. A peer's
load is never scaled up, so that pair isn't compared.

### 3. Rest

1. **A rest is only the available part of the time between two of a worker's shifts,** as in the scoring
   ([ADR 0038](0038-rests-count-only-available-time.md)).
   * Unavailability is neither work nor rest. Counted as rest, it would make shifts right around an absence free.
   * The time between periods counts as unavailable for everyone.
   * The legal minimum rest stays on the clock: it's a rule of what's legal, not something the audit judges.
   * The rests before a worker's first shift and after their last aren't judged.
2. **A rest is judged with the shifts around it,** as rest per hour of the two shifts: the rest divided by
   $(|s| + |s'|) / 2$, the shape of [ADR 0036](0036-rest-targets-from-the-input-convex-per-worker.md)'s target
   without its factor. This is the rest policy, not a value to tune; with shifts of equal length, it's just the rest.
   6 hours between a 12-hour and a 2-hour shift is shorter than 6 hours between two 2-hour shifts.
3. **Rests are compared against the best-off peer, rest by rest.**
   * Each worker's rests are sorted shortest first and compared with the peer's in the same places, up to the
     smaller number of rests.
   * Each place where the worker's rest is shorter is an event. How much shorter is a fact on it, in hours: how much
     longer it would have to be to match the peer's, for shifts this long.
   * There's no median, line or margin, so the same rests for everyone give no event, however long they are.
     Pairing the rests in any other order would give events even then.
4. **Every worker is a peer,** with no condition on shifts or availability. Rests aren't scaled: they're already
   measured in available time and per hour of work.

**Not taken:**
* **Comparing rests only with peers who did at least as many shifts,** to keep an extra shift from also showing as
  shorter rests. It would:
  * leave the worker with the most shifts unmeasured, and one rightly doing more (for being available longer) with
    no grievance of either kind;
  * turn a badly rested worker's rest events into one load event if they were given another shift;
  * be a claim about cause.

  The two are separate events, which can happen without each other: 3 shifts spread out can rest longer than 2 close
  together.
* **A short rest as a margin below the typical rest.** It's a cliff, uses a unit from the schedule with rough edges,
  and measures against a norm rather than a peer.
* **Judging rests against the worker's own load.** A worker resting 6 hours would have a grievance against one
  resting 4.

### 4. Easy fixes

1. **A fix is a nearby schedule:** the audited one with a few changes, in the new period only. A grievance about
   the history that has a fix is one the new period could have made up for.
   * The changes are moves (a slot given to another worker) and swaps (two workers exchanging slots in different
     shifts).
   * The nearby schedule must be legal.
   * The changes only describe how it differs, so their order doesn't matter. Every slot is always given to a worker
     with its role and available then, and a change may leave a worker holding two slots too close together (closer
     than the minimum rest, or overlapping) if the next change resolves it. Tests check the search against brute
     force on small inputs.

     *Corrected on 2026-11-20, in step 3:* this said the search reaches the nearby schedule one legal change at a
     time, in every order, and that tests would check that misses nothing. The brute-force test showed it misses
     fixes where two workers trade their shifts, since either swap alone leaves one of them with shifts too close
     together, in every order. Letting a conflict last one change finds them, at about twice the cost (a median of
     13 seconds on the stored tuning schedules, at most 152 on a 48-hour one, against 7 and 62). A conflict that
     only two later changes could resolve still isn't searched; brute force found none on the inputs tried.
   * The fix's size, its number of changes, is a fact on it.
2. **Only the nearby schedule is judged,** never each step on the way.
   * It's audited afresh by the same rules, with its own best-off peers. No line from the audited schedule is held
     steady.
   * It's compared with the audited one worker by worker and kind by kind, never across kinds.
   * **The grievance is gone:** the worker has fewer events of that kind (with that person, for partners).
   * **The worker is better off** in that kind's own terms: worse in none of its facts, and better in at least one.
     So making the peer worse off (levelling down) is no fix.
     * Load: no more shifts and no more hours, and fewer of one.
     * Rest: the new rests, compared with the old as with a peer's, none shorter and at least one longer.
     * Dislike: one shift fewer with that person.
     * Missing like: one more with them.
   * **The fix is harmless** if no worker, the aggrieved one included in other kinds, has more events of any kind, or
     a rest event larger when sorted by size.
3. **A fix that isn't harmless, a transfer, is reported too,** with exactly what it creates and for whom.
   * With no tolerance, most load fixes are transfers: the extra shift in a 2-2-3 split can only move.
   * A fix is dropped when another one creates a subset of what it creates, with no more changes. This is a set
     comparison, not an exchange rate.
   * A harmless fix creates nothing, so it drops every transfer of its size or larger.
4. **The search is complete up to K changes,** the smallest fix first. Its only shortcut can't lose a fix: at least
   one change must touch the grievance's workers.
   * "No fix" is an exact claim, always stated with its K ("no fix of up to 3 changes"). K sets how far the claim
     reaches, not what a grievance is.
   * **K is a command-line option** of the audit (and of `tools/tune.py`, which passes it on), 3 by default (a named
     constant). It isn't part of the input, which describes the schedule.
   * 0 turns the search off, with no claim about fixes either way.

   A lab check on 2026-11-19, with the old grievance definitions, showed why:
   * **On 200 samples of the example,** greedy chains found fixes for 2,522 of 3,131 complaints. Each of the other
     609 had a fix of 2 or 3 changes judged together.
   * **On the 75 stored tuning schedules,** 164 more complaints had a fix within 3 changes, besides greedy's 358.
     Most of their complaints are about the history. 10 complaints needed 4 changes or more.
   * **Requiring each step to be harmless and to narrow the complaint blocks preparing steps.** That's why seeds 150,
     165, 174 and 190 of the example had no fix at all: on three of them, at most 28 schedules can be reached by
     harmless steps. Yet each of their complaints has a fix of 2 or 3 changes.
   * **The cost of a complete search up to 3 changes** is up to about 5 minutes on a 48-hour schedule, and seconds on
     the example. Each change more multiplies the time by about the number of legal changes: about 30 on 24-hour
     schedules, 90 on 48-hour ones. 2 changes would miss over a quarter of what 3 adds to greedy chains (172 of 609
     on the example, 44 of 164 on the tuning schedules).

**Not taken:**
* **No cap on the chain:** the number of nearby schedules multiplies with each change.
* **Greedy chains:** they need each step to narrow the grievance, and whole events can only be removed.
* **No claim at all about grievances without a fix.**

### 5. The output

1. **A card per worker.** It shows their facts:
   * shifts and hours;
   * availability while a post is staffed;
   * their rests' available part, in hours;
   * their partners, with counts;
   * their liked pairings (the boon count, [ADR 0049](0049-partners-in-the-audit.md)).

   Then each event:
   * its kind;
   * what it points to: the extra shifts; the rest, with the shifts around it and who was in them; the shift and the
     disliked person; the peer's shift, for a missing like;
   * the peer it's measured against, with both sides' facts, in natural units;
   * its size, where it has one;
   * its smallest harmless fix with its size, or else its transfers, each with what it creates (all of them, one per
     line, until reading cards shows that's too long), or else "no fix of up to K changes". An event wholly in the
     history says so instead, since no change can reach it.

   K is printed at the top.
2. **The only totals are a closing table of counts,** per worker and per kind. Each cell gives the events, how many
   have a harmless fix, how many only transfers, and how many no fix within K.
   * Workers are in input order: ranking them would take a rule across kinds.
   * Nothing is added across kinds, and there are no severities.
3. **The audit returns its events, facts and fixes as data.** The command line prints the cards, or with `--json`,
   the same as JSON (the standard library's).
4. **`tools/tune.py` records, for each run, per kind:**
   * the events;
   * the most aggrieved worker's events (evenness);
   * the events with a harmless fix (the clearest sign the model chose worse than it could have).

   It also records the liked-pairings total and K. Its report shows each setting's measures side by side, kind by
   kind, with the settings it's dominated by: no better in any measure and worse in at least one. There's **no single
   ranking**, since any ranking across kinds is a weighing. Rows audited with different K values are flagged, never
   compared silently.
5. **`tools/audit_sample.py` compares per kind:**
   * the rank correlation of the penalty with each kind's events;
   * as disagreements, the samples best by penalty that still have harmless fixes, by kind.
6. **The audit stays independent of `csp/` and `scoring/`.** It imports `model/`, `parsing/`, `timing/` and the
   schedule checker, with its own legality check for fixes, so the model never grades itself.

### 6. What stays outside the audit

What matters more is decided where results are read, in tuning ([tuning](../explanation/tuning.md)), not in the
audit:
* one kind against another;
* evenness against the total ("most aggrieved first", with evenness as one input, not a fixed rule);
* which grievances could have been avoided.

The audit has no "unavoidable" label and no summary verdict, and sets no kind apart.

## Consequences

* **Grievances that look unavoidable stay on the cards.** A 2-2-3 split always shows one load event, with transfers
  only. The reading has to know that, as it has to know that the audit doesn't see levelling down.
* **Tuning has no single number to minimize.** Settings are compared kind by kind, with dominance, and the rest is a
  reading by the rules on the tuning page. Results audited before this ADR aren't comparable with those after; the
  stored tuning stages are audited again.
* **The audit is slower:** a complete fix search up to 3 changes takes up to about 5 minutes on a 48-hour schedule.
  K = 0 skips it.
* **Every rule is a sentence about how workers judge,** with no margin, tolerance or weight to tune. The named
  constants left only set how far a claim reaches (K) or how numbers are shown.
* **Checked by:**
  * a hand-made test for each decision, on inputs small enough to check by hand (a 2-2-3 split gives one load event
    with transfers only; equal rests give none; levelling down is no fix; the right transfers are dropped; peers'
    load scaled down only);
  * the fix search against brute force (every legal schedule within K changes) on small inputs;
  * identical audits on PyPy and CPython;
  * the finished tuning stages audited again, with every grievance that appears or disappears explained by a
    decision, the four seeds found to have fixes, and the time with K = 3 on 48-hour schedules measured;
  * cards read by hand, a sample brought to the user covering each kind, transfers, "no fix" and events in the
    history.
* **Replaced, from the audit page's earlier decisions:**
  * the tolerance;
  * the typical rest and its margin, and the audited schedule's norm for fixes (2026-11-12 and 2026-11-13);
  * short straws and the day window (2026-11-12 and 2026-11-13);
  * the greedy chains and their cap;
  * liked partners counted apart (2026-11-11, [ADR 0049](0049-partners-in-the-audit.md)).
