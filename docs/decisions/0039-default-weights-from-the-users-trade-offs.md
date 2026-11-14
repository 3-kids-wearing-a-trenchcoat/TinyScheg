# 0039. Default weights from the user's trade-offs: likes : workload : rest = 0.45 : 1 : 0.25, neutral partner 0.44

**Status:** Accepted. Amends [0032](0032-flat-penalty-parts.md) (the default weights) and
[0022](0022-scoring-parameters-with-defaults-and-input-overrides.md) (the default neutral partner).

## Context

The default weights (likes 0.57, workload 0.215, rest 0.215, [ADR 0032](0032-flat-penalty-parts.md)) and neutral
partner (1/3) were set before the rest part changed: its targets are now derived from the input and each worker's
shortfall is squared ([ADR 0036](0036-rest-targets-from-the-input-convex-per-worker.md)), with the worst case counted
over the whole history ([ADR 0037](0037-worst-rest-deficit-from-scratch-over-the-history.md)) and rests in available
time only ([ADR 0038](0038-rests-count-only-available-time.md)). Squaring made small shortfalls cheap and large ones
dear, so the balance between the parts had moved.

The audit is one fallible tool among others, so the re-check weighed the evidence in this order
([tuning](../explanation/tuning.md#what-better-means)): the user's rules, as checks; measures that don't come from
the audit; then the audit. The user's rules (2026-11-14):

* A like means "I would be okay with doing an earlier shift to be posted with them" (one shift sooner), a dislike the
  same "to avoid being posted with them": each is worth about one short rest. It justifies "getting screwed over
  once", but "shouldn't be a persistent punishment": it can't make up for a worker's second short rest.
* "A 2-2-2 distribution of work is fair, a 2-2-3 is still fair because 'someone has to be screwed over' [...] a 2-2-4
  distribution is an outrage and cannot be made up for with a liked worker." A 2-2-4 can "virtually always" be
  rebalanced into 2-3-3, so made by hand it would be an oversight.
* "One worker resting at a minimum is acceptable, 2-2-4 is virtually never acceptable": one worker resting at the
  minimum twice costs less than a 2-2-4.
* A dislike weighs a little more than a like, only so that "A likes B, B dislikes A" is a net penalty
  ([ADR 0023](0023-dislikes-outweigh-likes.md)).

At the old defaults, an avoidable gap of two shifts cost less than three dislikes, and about a third of one worker
resting at the minimum twice.

## Decision

The default weights are **likes : workload : rest = 0.45 : 1 : 0.25**, stored scaled to add up to 1 (9/34, 20/34 and
5/34), and the default **neutral partner is 0.44**. The shift share stays 0.5, and the workload power 2.

What one event costs on the example (the input the scoring docs use), for an average worker and an average shift,
weighted:

| Event | Old defaults | New defaults |
|---|---|---|
| A like, instead of a neutral partner | 0.19 | 0.12 |
| A dislike, instead of a neutral partner | 0.38 | 0.15 |
| A worker's first short rest (an average shift's length below target) | 0.18 | 0.12 |
| Their second | 0.53 | 0.36 |
| One worker resting at the minimum twice | 1.25 | 0.85 |
| An avoidable gap of two shifts | 0.43 | 1.18 |

At the new defaults, a like is worth 0.97 short rests and a dislike 1.27 likes; a second short rest outweighs any one
pairing; and a gap of two shifts costs about as much as 8 dislikes, and 1.38 times one worker resting at the minimum
twice. The rules are tested at the defaults (`tests/test_default_tradeoffs.py`) and checked for every setting in the
tuning report.

How the values were found:

* The likes weight sets a like against a short rest, and the neutral partner a dislike against a like, so both come
  from the user's exchange rates rather than from the audit.
* The workload weight comes from the two outrage rules. Outweighing three pairings needs about 0.38 (with rest at
  0.25); outweighing one worker resting at the minimum twice needs 0.75 on the example, with no margin. 1.0 gives
  1.38 times; 1.25 gives 1.72, but its search was the slowest and didn't finish one tuning input in 10 minutes.
* Rest 0.25 rather than 0.3 keeps a like at one short rest (0.81 at 0.3) and the outrage's margin larger.

Measured on the 8 tuning inputs, each alone and as the first of two periods (rounds `s2-weights`, `s3-candidates` and
`s3b-workload`):

* A workload weight of 0.75 or more removes the last avoidable gap of two shifts that the old defaults and the
  lighter candidates left (`sweep_02`, two complaints with an easy fix); that schedule also has fewer rests at the
  minimum and a smaller gap in hours, and two fewer liked pairings. 0.75, 1.0 and 1.25 give the same schedule on
  every input alone.
* A shift share of 0 (hours only) gave larger gaps in shift counts between workers, which the rest part can't keep
  even where short shifts' targets sit at the minimum; it stays 0.5 for now
  ([future work](../explanation/future-work.md#workload-in-hours-only)).

Checked on the 7 held-back and confirm inputs (`s4-check`): the same schedules as the old defaults on most, better on
two (fewer complaints with an easy fix on `sweep_12`; a better second period on `confirm_02`), worse on none, and no
2-2-4 on the two loosest.

## Consequences

* The search takes longer: 3–7 times as long as at workload 0.38 on the held-back and confirm inputs, and on
  `confirm_01` (24 hours, 12 workers) about 2.3 hours to prove the best schedule (found after 4.4 minutes), against 7
  minutes. The likely cause is the workload bound, which spreads the remaining work as if it could be split finely,
  a gap the workload weight multiplies; a bound in whole slots is the next step
  ([future work](../explanation/future-work.md#search-performance)).
* The rules hold on the example. On other inputs the trade-offs differ, most of all for rest: resting at the minimum
  costs the square of how far the minimum sits below the schedule's targets, while a gap of two shifts costs the same
  whatever the targets. On the two loosest benchmark inputs, `confirm_01` and `confirm_03` (targets 6.6–7.5 hours
  above the minimum), a 2-2-4 costs 0.58 and 0.48 times one worker resting at the minimum twice. Since a 2-2-4 can
  virtually always be rebalanced, and rebalancing usually helps rest too, the two rarely compete; neither input had a
  2-2-4.
* A first period that's better alone can leave the next one worse (`sweep_02`;
  [future work](../explanation/future-work.md#a-schedule-that-leaves-the-next-one-with-no-legal-schedule)).
* Inputs that set all three weights aren't affected; one that sets only some of them gets the new defaults for the
  rest, before the weights are divided by their sum.
