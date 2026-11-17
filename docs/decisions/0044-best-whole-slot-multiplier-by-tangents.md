# 0044. The whole-slot bound's best multiplier, found exactly by tangents

**Status:** Accepted. Amends [0040](0040-workload-bound-in-whole-slots.md) (the search for $\mu$).

## Context

The workload bound in whole slots ([ADR 0040](0040-workload-bound-in-whole-slots.md)) is the highest value of

$$LB(\mu) = \mu R + \sum_w \min_{z \in T_w} \bigl(f_w(z) - \mu z\bigr)$$

over the multiplier $\mu$. Every $\mu$ gives a valid bound, so ADR 0040 tried a few: it bracketed the best one from the
water level's marginal cost in at most `MU_STEPS` (3) steps of `MU_GROWTH` (1.5) times, then halved the bracket 3
times, about 5 tries in all. That rarely lands on the best $\mu$, and the bound is weaker than it could be.

Measured outside the program (Phase 11 step 1, 2026-11-16; see
[Future work](../explanation/future-work.md#search-performance)), the best $\mu$ would leave 0–44% fewer nodes on inputs
searched to the end, and on the slow 48-hour inputs, 1.0–34 times the progress in the same number of nodes. It
changes no result: a higher valid bound prunes only branches that can't beat the pocket.

Two ways of finding the best $\mu$ exactly were compared (2026-11-17, in a lab script outside the program), on about
127,000 states recorded from the program's searches on 8 inputs, and then in whole searches of 16 inputs to the end
and 3 48-hour ones up to 20 million nodes:

* **The envelope** (the plan): the highest $LB(\mu)$ equals the lowest cost of the convexified problem, in which each
  worker's cost is the lower convex envelope of their points $(z, f_w(z))$, $z \in T_w$. Each worker's envelope is
  built, and the segments of all workers are taken in order of slope until $R$ is handed out.
* **Tangents:** $LB$ is concave and piecewise linear in $\mu$ (a minimum of lines, one per point of each $T_w$), and
  the evaluator ADR 0040 already has gives at each $\mu$ both its value and its slope, $R$ less the load the
  per-worker minimizers hand out. The search uses the tangent lines at the ends of a bracket.

Both give exactly the best value on every recorded state, against a long bisection, so their searches visit the same
nodes. They differ in cost:

| | Time per bound, PyPy (per input) | 16 inputs to the end, PyPy | 48-hour inputs, PyPy | 6 small inputs, CPython |
|---|---|---|---|---|
| ADR 0040's ~5 tries | 3.0–9.5 µs | | | |
| Envelope | 4.4–98 µs | 858 s | 0.27–0.40 times the tangents' progress per second | 114 s |
| Tangents | 2.5–12.9 µs | 342 s | 1 | 133 s |

The envelope's cost grows with the number of slots left, so it's at its worst on long schedules, where speed matters
most. It's fastest on CPython's small inputs only, where sorting is cheap compared with plain Python, and PyPy is the
intended runner ([ADR 0033](0033-pypy-for-development-runs.md)).

## Decision

**The best $\mu$ is found by tangents**, in `whole_slots._best_over_mu`, from the same evaluators (the exact
combinations or the intervals) and the same sets $T_w$ as before:

1. **The rising end:** at $\mu = 0$ nobody takes anything (each term rises with the worker's load), so
   $LB(0) = \sum_w f_w(0)$, computed directly, and its slope is $R$.
2. **The falling end:** from the water level's marginal cost, $\mu$ is multiplied by `MU_GROWTH` (2) until the slope
   turns negative. Each $\mu$ tried on the way whose slope is still positive becomes the rising end.
3. **Tangent steps:** with a rising end $(\mu_1, v_1, s_1)$ and a falling end $(\mu_2, v_2, s_2)$, the tangent lines
   $v_1 + s_1 (\mu - \mu_1)$ and $v_2 + s_2 (\mu - \mu_2)$ cross at

   $$\mu^* = \frac{v_2 - v_1 + s_1 \mu_1 - s_2 \mu_2}{s_1 - s_2}$$

   Since $LB$ is concave, it lies below both tangents, so no $LB(\mu)$ is above their crossing's height
   $c = v_1 + s_1 (\mu^* - \mu_1)$. $LB(\mu^*)$ is evaluated:
   * if it reaches $c$, up to a relative `OPTIMUM_GAP` ($10^{-12}$), it's the highest value, and the search stops;
     also where its slope is 0;
   * otherwise $\mu^*$ replaces the end whose slope has the same sign, and the step repeats.

   $LB$ is made of finitely many lines, and each step's $\mu^*$ lies inside the bracket, which narrows onto the
   kink where the slope changes sign. On the recorded states it took 3–6 evaluations per bound beyond $\mu = 0$
   (2.7–6.4 on average per input), and every bound was certified.
4. **Safeguards:** at most `MAX_MU_STEPS` (60) evaluations, and a stop where rounding leaves the bracket unable to
   narrow. If no $\mu$ makes the slope negative, no completion exists. In every case the highest value found is
   returned, which is a valid bound.

The rest of ADR 0040 is unchanged: the sets, the rounding margin, where the bound doesn't apply, and the cheap
water-filling bound checked first. `MU_STEPS` is gone.

## Consequences

* **The same results:** a higher valid bound only prunes more of what can't beat the pocket.
  * Tests: the value equals a long bisection's on random cases, with exact and interval sets, powers 2 and 3; a
    function known by hand; and the existing ones: never above brute force's best whole-slot completion, the same
    search result with and without the bound.
  * On every benchmark input, alone and as day 2, on CPython and PyPy, the schedules are identical to the recorded
    ones (2026-11-17).
* **Faster** (2026-11-17, the program's own code against `dev`'s, one process, six searches at a time; the searches
  were the same as above):
  * PyPy, the 16 inputs searched to the end: 398 s in all to 351 s (12% less), with 0.56–1.00 of the nodes.
  * PyPy, the 48-hour inputs up to 20 million nodes: 1.70 times the progress per second on `multiday_04`, 1.71 on
    `multiday_05`, 1.27 on seed 3009.
  * CPython, 6 small inputs: 158 s to 134 s (15% less).
  * With 12 processes on PyPy, the 15 benchmark inputs took 57 s alone and 50 s as day 2, against 62 s and 53 s in the
    laptop baseline of 2026-11-16; these short runs are mostly start-up.
* **Each bound costs a little more** where it prunes no more than before: on `sweep_11`, the same nodes took about 12%
  longer (3 runs each). `MU_GROWTH` and `OPTIMUM_GAP` are the dials if that's ever worth tuning.
* **Not taken:** the envelope, kept in the lab script of 2026-11-17 (outside the repository), in case a CPython
  distribution ([ADR 0033](0033-pypy-for-development-runs.md)) ever makes small inputs on CPython the case to
  optimize.
