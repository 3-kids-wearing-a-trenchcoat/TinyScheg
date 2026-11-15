# Tuning the scoring

How the [scoring parameters](scoring.md#parameters) get their default values: by comparing the best schedules they
produce with the [schedule audit](schedule-audit.md), on a set of benchmark inputs. The values found are a starting
point, not final, but they shape how every later output is read, so the method is recorded here.

> [!IMPORTANT]
> **Partially implemented.** The benchmark generator (`tools/benchmarks/generate.py`) and the tuning runner
> (`tools/tune.py`) exist and are tested. The first round set the default rest factor to 2.5
> ([ADR 0028](../decisions/0028-rest-factor-default-2-5.md)), since superseded: the rest factor is now derived from
> the input, and each worker's shortfall squared
> ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)). The weights were then checked
> again, and set from the user's trade-offs
> ([ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md); see
> [the weight re-check](#the-weight-re-check-2026-11-14)). Longer schedules are still to be checked.

> [!WARNING]
> **The audit changed on 2026-11-13** (load compared with no exchange rate between shifts and hours, shifts counted in
> every day they overlap, short rests judged by the audited schedule's norm, and no fix that hands out a new short
> straw; see [the audit](schedule-audit.md#load)). Every result on this page from before then was measured with the
> old audit, so its numbers aren't comparable with later ones. The conclusions drawn from them have since been
> replaced: the rest factor by one derived from the input
> ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)), and the weights by the re-check
> with the new audit ([ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)).

## What's tuned, against what

The five independent parameters: the weights of likes, workload and rest (two independent values, since only their
ratios matter), the workload power $p$, the neutral partner value $\alpha / \beta$,
which stays below 1/2 ([ADR 0023](../decisions/0023-dislikes-outweigh-likes.md)), and the shift share $\sigma$
([ADR 0026](../decisions/0026-workload-counts-shifts-and-hours.md)). The rest factor $\gamma$ was a sixth until it
became derived from the input ([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)).

The yardstick is the audit, **held fixed**: its own thresholds aren't tuned, or the two would just drift towards each
other. Since branch and bound gives the proven best schedule for each setting, any difference in the result comes
from the parameters, not from search luck.

## What "better" means

Revised on 2026-11-14, for the weight re-check after the rest part changed
([ADR 0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md)): the audit is one fallible tool among
others, so the evidence is weighed in this order.

1. **The user's rules**, as checks each setting passes or fails. A like or a dislike is worth one short rest (a shift
   one slot sooner), once: it can make up for one short straw, or for being the one who has to take the extra shift in
   an unavoidable 2-2-3, but not for a worker's second short rest, and no number of them for an avoidable two-shift
   gap ("2-2-4 is an outrage"); one worker resting at the minimum twice is acceptable, a 2-2-4 "virtually never"
   (it can virtually always be rebalanced into 2-3-3); a dislike weighs a little more than a like, only so that "A
   likes B, B dislikes A" is a net penalty ([ADR 0023](../decisions/0023-dislikes-outweigh-likes.md)). These are
   checked on each setting's [unit trade-offs](#whats-recorded), along with the history test (a worker idle in the
   history makes up for it).
2. **Measures that don't come from the audit**, input by input, alone and over two periods: rests at the minimum,
   the spread of workers' shortest rests, the gaps in hours and shifts between peers (a one-shift gap is fine where it
   can't be helped, two is an outrage), liked and disliked pairings, and whether the second period still has a legal
   schedule.
3. **The audit**, by the priorities decided on 2026-11-11: severity with an easy fix (unfairness that could easily
   have been avoided), then concentration (unfairness shouldn't pile up on one or two workers), then total severity,
   including complaints with no easy fix, as a tie-breaker.

The measures aren't collapsed into one number; trade-offs between them are a decision, not a calculation.

## What's recorded

For each setting and input, `tools/tune.py` finds the best schedule and audits it, then continues the input for a
second period of the same length, right after the first and with the first's schedule as its history (the same
workers and posts, each worker's unavailability repeated a period later), finds the best schedule of that and audits
the whole of both (the `day2_` columns). A first period that leaves the second no legal schedule is recorded as day
2's `no schedule`: a failure, since in real use the next schedule couldn't be made
([future work](future-work.md#a-schedule-that-leaves-the-next-one-with-no-legal-schedule)).

Besides the audit's measures, each schedule gets measures that don't come from the audit, over the whole schedule
(both periods for day 2): each rest in available time
([ADR 0038](../decisions/0038-rests-count-only-available-time.md)), how many are at or below the minimum rest, their
median, the spread of the workers' shortest rests, the largest gaps in hours and in shifts between fully available
workers, and the pairings in shared shifts with someone a worker likes or dislikes (each worker's view counted).

Each setting's **unit trade-offs** are computed from the formulas on the example input, for an average worker and an
average shift: what a like and a dislike cost (each instead of a neutral partner), a first and a second short rest
(an average shift's length of rest less, each), one worker resting at the minimum twice (between two average
shifts), one extra shift (taken on by everyone else) and an outrage (one shift moved between two equal workers, a
gap of two), all weighted. The report checks the user's rules on them (`RULE_CHECKS`): an outrage must outweigh
`OUTRAGE_PAIRINGS` (3) likes or dislikes, and one worker resting at the minimum twice; a worker's second short rest
must outweigh a like or a dislike; and a like must be worth one short rest, within `LIKE_PER_SHORT_REST_FACTOR`
(1.25) either way. It also shows a dislike per like (a little over 1) and an outrage per twice at the minimum. The
same checks are tests of the defaults (`tests/test_default_tradeoffs.py`).

## Benchmark inputs

What counts as realistic changes from one deployment to the next, so there's no standard setup. Every benchmark
input has at least 2 posts, at least 6 workers, a post needing more than one worker some of the time, and some
workers who like or dislike others; everything else varies. Most are **loose**: in practice the hard schedules are
the ones with many legitimate choices, where every choice invites "why didn't you do this instead?", not the
constrained ones that decide themselves.

`tools/benchmarks/generate.py` draws each input from a seed (the knobs are named constants at its top). The sweep
tier, which the parameters are chosen on, gives each worker several shifts, so that the audit has unevenness to see;
the longer tiers are staffed more generously:

| Knob | Sweep tier | Confirm and multiday tiers |
|---|---|---|
| Length | 16, 20 or 24 hours | 24 hours (confirm), 48 (multiday) |
| Start time | 00:00, 08:00 or 16:00 | same |
| Posts | a gate that always has a shared shift (a 19:00–07:00 variation needing a role and one more worker, or 2 workers throughout); a desk needing one role, sometimes only 08:00–20:00; sometimes a patrol of 2 | same |
| Gate shift length | 2 hours | 3 or 4 hours |
| Roles (`medic`, `driver`) | common (half the first workers) | each common three times in four, otherwise scarce (3 holders) |
| Unavailability | one worker in ten has one block of 2, 4 or 8 hours | one in five |
| Preferences | sparse, medium or dense likes and dislikes; at least 2 workers have some | same |
| Staffing | start at 6 workers and add workers until a legal schedule exists (at most 12), then add 1 or 2 more | the same, then add 2–5 more (loose), or none for one input in five (tight) |
| Minimum rest | 6 hours | same |

An input is kept only if branch and bound finds its best schedule within the tier's time limit (5 minutes for the
sweep tier, 10 minutes for the others). Candidates are tried in parallel but taken in seed order, so the inputs kept
don't depend on how many are tried at once; a solve may run slightly slower when the machine is busy, though. This quietly drops the loosest inputs, which take longest to search; the manifest
(`tools/benchmarks/manifest.csv`) lists every skipped candidate and why, so the bias stays visible. Every third input
of a tier is **held back**: never used to choose values, only to check the chosen ones at the end. The inputs are
committed, so changing the generator never silently changes what was tuned on.

## Stages

Run with `tools/tune.py`, which finds and audits the best schedule for each input at each setting, many in
parallel. Each run's result is appended to `tools/benchmarks/results/<stage>.csv` as it finishes, so a stage can be
stopped and resumed, and `python tools/tune.py status` shows how far along it is. Each row keeps its best schedule,
so after a change to the audit, `python tools/tune.py reaudit STAGE` audits a finished stage again without
searching again.

1. **Baseline** — the defaults, on every input. Each complaint with an easy fix is then diagnosed by breaking the
   fixing change's penalty difference down by part: a **parameter** question (e.g. likes weighed too low against
   rest) is for tuning; a **formula** question (e.g. averaging that rewards concentrating good pairings) is a design
   decision, needing its own ADR, since no parameter setting can fix it.
2. **Sensitivity** — one parameter at a time over a range, the others at their defaults, on the tuning inputs: which
   parameters matter, and over what range.
3. **Rounds, by hand** — a few candidate settings at a time, chosen from what the earlier stages showed, run on the
   tuning inputs, read, and adjusted for the next round, until the complaints stop dropping: the aim is fewer
   complaints, not none. Each round is its own stage, named on the command line:
   `python tools/tune.py round NAME --setting neutral_partner=0.25,shift_share=0.5 --setting ...`, where each setting
   names only the parameters it changes from the defaults, and `--inputs holdout` or `--inputs confirm` runs it on
   the held-back inputs or the confirm tier instead (report it with `--holdout` to include the held-back ones).
   Running a round again with more settings adds them. There's no automated search over the parameters: which
   values to try next is a judgement made from the results and the feedback cards.
4. **Choice and check** — a few candidate settings, checked on the held-back inputs and the longer tiers, with the
   feedback cards of some schedules read by hand: the audit models the workers, but isn't them. The chosen defaults
   then go in as named constants, with an ADR.

## The weight re-check (2026-11-14)

After the rest part changed (ADRs [0036](../decisions/0036-rest-targets-from-the-input-convex-per-worker.md) to
[0038](../decisions/0038-rests-count-only-available-time.md)), four rounds, judged in the order above; the defaults
that came out are in [ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md).

1. **`s2-weights`** (15 weight settings, tuning inputs): alone, the best schedule barely changed with the weights (one
   to three distinct schedules per input); over two periods, a rest weight of 0.15 or less was clearly worse (more
   rests at the minimum, more severe easy fixes, a second period with no legal schedule), and 0.4 or more too (more
   complaints, fewer liked pairings, a like worth half a short rest). Between them the benchmark couldn't tell
   settings apart, so the user's rules decided.
2. **`s3-candidates`** (three candidates that pass the rules for likes, each with the shift share at 0.5, 0.25 and 0):
   a shift share of 0 gave larger gaps in shift counts and more severe easy fixes; 0.5 kept. The candidates were
   indistinguishable.
3. **`s3b-workload`**, for the rule that one worker resting at the minimum twice is acceptable and a 2-2-4 virtually
   never (likes 0.45, neutral partner 0.44, the workload weight from 0.75 to 1.25, rest 0.25 or 0.3): from 0.75 up,
   the last avoidable 2-2-4 on the tuning inputs (`sweep_02`) disappears; 0.75, 1.0 and 1.25 give the same schedule
   on every input alone, so the rules' margins decided: 1.0 with rest 0.25.
4. **`s4-check`** (the choice, C1 at workload 0.38 and the old defaults, on the held-back and confirm inputs, with a
   30-minute limit per solve): the same schedules as the old defaults on most inputs, better on two, worse on none;
   no 2-2-4 on the two loosest inputs, where the rule's margin is lowest. The search took 3–7 times as long as at
   workload 0.38, and didn't prove the best schedule of `confirm_01` within the limit (an uncapped run took 1.9
   hours). The workload bound in whole slots ([ADR 0040](../decisions/0040-workload-bound-in-whole-slots.md)) then
   brought it to 4½ minutes, with the same schedules on every input.

A first period that's better alone can leave the next one worse: on `sweep_02`, from the same first period every
setting gave the same second, and by the chosen setting's own scoring, the two periods together were better after
workload 0.38's first period, avoidable gap and all
([future work](future-work.md#a-schedule-that-leaves-the-next-one-with-no-legal-schedule)).

## Known limits

* Tuning to the audit's quirks: reading cards by hand at the last stage guards against it.
* The user's rules are checked on the example. On other inputs the trade-offs differ, most of all for rest: what
  resting at the minimum costs grows with how far the minimum sits below the schedule's targets, so on the loosest
  inputs a 2-2-4 costs less than one worker resting at the minimum twice
  ([ADR 0039](../decisions/0039-default-weights-from-the-users-trade-offs.md)).
* The easy-fix search is greedy, so severity with an easy fix is slightly noisy; many inputs smooth that out.
* Benchmarks are small (16–24 hours) so that branch and bound finishes; the longer tiers check that results carry
  over. Since a period of 24 hours or less is itself the day, the audit's load in any day only adds anything on
  longer inputs, so load within a day can only be studied on 48-hour inputs. Those are now within reach: with the
  parallel search ([ADR 0041](../decisions/0041-parallel-search-with-the-sequential-result.md)), the 48-hour example
  takes about 12 minutes on PyPy (2026-11-15).
