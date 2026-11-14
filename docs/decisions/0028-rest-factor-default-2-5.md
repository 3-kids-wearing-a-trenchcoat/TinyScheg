# 0028. Default rest factor 2.5

**Status:** Superseded by [0036](0036-rest-targets-from-the-input-convex-per-worker.md).

## Context

The rest factor $\gamma$ sets the rest target after a shift $s$ at $\gamma \cdot |s|$
([Scoring](../explanation/scoring.md#rest)). Its default of 3 was chosen in
[ADR 0022](0022-scoring-parameters-with-defaults-and-input-overrides.md) before any schedule had been audited. The
first round of [tuning](../explanation/tuning.md), on 2026-11-12, compared it against the
[schedule audit](../explanation/schedule-audit.md), which judges each schedule by the norms it sets itself:

* **Sensitivity** (one parameter at a time, on the 8 tuning inputs): $\gamma = 2.5$ was the clearest improvement of
  any parameter. It fixed the input with the most severity left (`sweep_02`), made no input worse, and timed out on
  none. Lower values (1.5–2) and higher ones (4–5) were worse or slower. Other parameters mattered little (the
  likes share up to 0.4, the rest share, the neutral partner) or cost too much search time (workload power 3–4).
* **Round 2:** combined with the shift share at 0.25 instead of 0.5, the `sweep_02` fix was lost: the workload term
  became too weak against likes. So only $\gamma$ changes.
* **Check** on inputs not used to choose it (the 4 held-back sweep inputs and the 3 24-hour confirm inputs), after
  the audit's day windows were corrected to any 24 hours rather than calendar days:

| | $\gamma = 2.5$ | $\gamma = 3$ |
|---|---|---|
| Severity with an easy fix, tuning inputs | 0.00 | 0.25 |
| Severity with an easy fix, held-back and confirm inputs | 0.29 | 0.57 |
| Concentration, held-back and confirm inputs | 0.07 | 0.21 |

$\gamma = 2.5$ was no worse on any single input. The feedback cards left were read by hand: one complaint with an
easy fix remains (three short shifts against one long one, whose fix costs rest and likes, an acceptable trade-off),
and one without (extra load forced by a role).

Why it helps: after the short (about 2-hour) shifts common in asymmetric schedules, $\gamma = 3$ asks for 6 hours'
rest or more, so a rest of exactly the minimum is penalized, although in such schedules it's the norm. With
$\gamma = 2.5$, those targets fall below the minimum rest and stop counting, while longer shifts still get rest targets well
above it. The rest penalty then stops competing with workload over rests nobody would complain about.

## Decision

The default rest factor is **2.5** (`DEFAULT_REST_FACTOR`). The other defaults stay as they are. Inputs can still
set `rest_factor` themselves.

## Consequences

* Short shifts (up to $m / 2.5$ hours, 2.4 hours with 6 hours' minimum rest) no longer have a rest target above the
  minimum rest, so they can't cause a rest deficit. Rest after them is still bounded by the minimum rest, a hard
  constraint.
* Schedules written with the defaults change, as with any change to the scoring.
* The values were chosen on schedules of 16 to 24 hours, the longest the search could finish. Whether they carry
  over to longer schedules, where load within a day matters separately from load overall, is still to be checked.
* Tuning is done by hand, in rounds, aiming to minimize complaints rather than to eliminate them; later rounds may
  revise this value, with a new ADR.
