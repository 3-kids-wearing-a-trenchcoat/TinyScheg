# 0047. Choosing the role-aware bound: on, off, or automatically from the input

**Status:** Accepted. Amends [0046](0046-whole-slot-sets-from-each-workers-own-domain.md) (when its sets are used).

## Context

The whole-slot bound's sets from each worker's own domain ([ADR 0046](0046-whole-slot-sets-from-each-workers-own-domain.md),
"the role-aware bound") prune much more where roles and unavailability narrow the domains: half the nodes on
`sweep_08` and `sweep_12`, 60–71 times the progress on `multiday_05`. Elsewhere they prune nothing more, and keeping
each worker's counts costs about a fifth more time per node (`sweep_06` 35% slower, `multiday_04` 0.9 times the
progress). The user asked (2026-11-17) for a setting to force it on or off, and for the program to choose by itself
when it isn't set.

## Decision

1. **A setting, `role_aware_bound`: `auto` (the default), `on` or `off`,** in the input's `settings`, and as the
   command-line option `--role-aware-bound`. **The command line wins** where both are given (the user's rule for
   every option offered in both places). It changes how fast the search finishes, never the schedule.
2. **Off is the global sets of ADR 0040, at their old cost:** the scorer keeps either the count of unfilled slots of
   each load overall (off) or each worker's counts (on), never both, and the bound uses the matching sets. Off visits
   exactly the nodes the program visited before ADR 0046, and on exactly the nodes it visits with it.
3. **The choice is resolved once per run, in the scoring constants** (`ScoringConstants.own_whole_slot_sets`, by
   `uses_own_whole_slot_sets`), which every place that computes the bound already receives: the incremental scorer,
   the bound from scratch near a tie, and every process of the parallel search.
4. **Auto turns it on where the domains are narrowed in more than one way:** where the slots' domains are of at least
   `AUTO_MIN_DISTINCT_DOMAINS` (3) kinds, and at least `AUTO_MIN_LOAD_OUTSIDE` (0.2) of the load lies outside them
   (each slot's load times the share of workers who can't take it, over the load times the number of workers). It
   reads the domains `build_constants` receives (with a history, those of its slots too: who could have filled
   them). It takes a few microseconds.
5. **The command line says what was used,** before the search: `role-aware bound: on (chosen from the input)`.

### How the rule was chosen

On the benchmark inputs, alone and as day 2, searched with it on and off (2026-11-17, PyPy, one process, four at a
time), the time with it on followed its node savings: it paid only where it saved about a fifth of the nodes or more.
Candidate measures of the input, computed from the domains before the search:

* With only 2 kinds of domain (everyone, and a role's holders), it never saved a node (`sweep_02`, `_03`, `_04`,
  `_06`, `_07`): the caps already say as much.
* With more kinds, the savings varied (none on `sweep_11`, half on `sweep_12`); the share of the load outside the
  domains separated most of the rest. The gap between the two bounds at the start was about 0 everywhere, as the
  pruning that matters is deep in the tree, and so was no guide.
* On these 30 comparisons, the rule chose the faster one 24 times: 432 s in all, against 469 s always off, 472 s
  always on, and 425 s choosing right every time.

Not taken: a trial run of each for a while (costly on every run, noisy early on, and its choice could depend on
timing); deciding from the bounds at the start (no guide).

## Consequences

* **The same results** with any setting: tests run the search on, off and auto on the small brute-force inputs, the
  incremental bound equal to the one from scratch with either sets; the reader, the setting's validation, the
  command line's precedence, and the rule on constructed domains are tested too.
* **Checked on inputs the rule wasn't fitted on** (the user's check, 2026-11-17): freshly generated inputs, each
  searched with it on and off (alone and as day 2; the 48-hour ones up to 10 million nodes, by progress per second).
  Of 17 comparisons, auto chose the faster one 15 times. Searched to the end, 286 s with auto, 284 s always off, 328 s
  always on, 283 s choosing right every time; the two wrong choices cost 0.04 s and 3 s, and it kept off every input
  where on was much slower (115 s against 140 s, 42 s against 48 s, 70 s against 77 s; the three 48-hour inputs,
  where on made 0.83–0.88 times the progress). None of these inputs was one where on wins much, so the rule's
  choosing on (for `sweep_08`, `sweep_12`, `confirm_01`, `multiday_05`, seed 3009 among the fitted ones) is checked
  only on the inputs it was fitted on.
* **Deciding costs nothing measurable:** 1–6 µs per run, against searches of seconds to hours.
* With 12 processes, the benchmark inputs gave the recorded schedules alone and as day 2 with auto, the default.
* **The rule is fitted on a few dozen inputs** and its thresholds are named constants, to revisit as more inputs are
  tried; where it chooses wrong, the setting overrides it.
