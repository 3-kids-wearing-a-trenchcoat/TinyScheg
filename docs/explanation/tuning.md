# Tuning the scoring

How the [scoring parameters](scoring.md#parameters) get their default values: by comparing the best schedules they
produce with the [schedule audit](schedule-audit.md), on a set of benchmark inputs. The values found are a starting
point, not final, but they shape how every later output is read, so the method is recorded here.

> [!IMPORTANT]
> **Partially implemented.** The benchmark generator (`tools/benchmarks/generate.py`) and the tuning runner
> (`tools/tune.py`) exist and are tested. The first round is done: the default rest factor became 2.5
> ([ADR 0028](../decisions/0028-rest-factor-default-2-5.md)). Longer schedules are still to be checked.

> [!WARNING]
> **The audit changed on 2026-11-13** (load compared with no exchange rate between shifts and hours, shifts counted in
> every day they overlap, short rests judged by the audited schedule's norm, and no fix that hands out a new short
> straw; see [the audit](schedule-audit.md#load)). Every result on this page from before then was measured with the
> old audit, so its numbers aren't comparable with later ones, and the conclusions drawn from them (the rest factor,
> the weights) may need checking again.

## What's tuned, against what

The six independent parameters: the weights of likes, workload and rest (two independent values, since only their
ratios matter), the workload power $p$, the rest factor $\gamma$, the neutral partner value $\alpha / \beta$,
which stays below 1/2 ([ADR 0023](../decisions/0023-dislikes-outweigh-likes.md)), and the shift share $\sigma$
([ADR 0026](../decisions/0026-workload-counts-shifts-and-hours.md)).

The yardstick is the audit, **held fixed**: its own thresholds aren't tuned, or the two would just drift towards each
other. Since branch and bound gives the proven best schedule for each setting, any difference in the result comes
from the parameters, not from search luck.

## What "better" means

Decided before looking at any numbers (2026-11-11), in this order:

1. **Severity with an easy fix**, as low as possible: unfairness that could easily have been avoided.
2. **Concentration**: unfairness shouldn't pile up on one or two workers.
3. **Total severity**, including complaints with no easy fix, only as a tie-breaker: much of it is unavoidable.

The measures aren't collapsed into one number; trade-offs between them are a decision, not a calculation.

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
   `python tools/tune.py round NAME --setting rest_factor=2.5,shift_share=0.5 --setting ...`, where each setting
   names only the parameters it changes from the defaults, and `--inputs holdout` or `--inputs confirm` runs it on
   the held-back inputs or the confirm tier instead (report it with `--holdout` to include the held-back ones).
   Running a round again with more settings adds them. There's no automated search over the parameters: which
   values to try next is a judgement made from the results and the feedback cards.
4. **Choice and check** — a few candidate settings, checked on the held-back inputs and the longer tiers, with the
   feedback cards of some schedules read by hand: the audit models the workers, but isn't them. The chosen defaults
   then go in as named constants, with an ADR.

## Known limits

* Tuning to the audit's quirks: reading cards by hand at the last stage guards against it.
* The easy-fix search is greedy, so severity with an easy fix is slightly noisy; many inputs smooth that out.
* Benchmarks are small (16–24 hours) so that branch and bound finishes; the longer tiers check that results carry
  over. Since a period of 24 hours or less is itself the day, the audit's load in any day only adds anything on
  longer inputs, so load within a day can only be studied on 48-hour inputs, if any finish.
