# 0046. The whole-slot bound's sets from each worker's own domain

**Status:** Accepted. Amends [0040](0040-workload-bound-in-whole-slots.md) (the sets $T_w$).

## Context

The workload bound in whole slots ([ADR 0040](0040-workload-bound-in-whole-slots.md)) finds each worker's lowest cost
over a set $T_w$ holding every extra load they could get. Its sets counted the remaining slots of each load overall:
any whole number of them, no more of each load than remain, at most $\lfloor \mathrm{cap}_w / u \rfloor$ slots and
at most $\mathrm{cap}_w$ in all. So a worker who can take only one 4-hour slot, with 1-hour slots left that only
others can take, could still be given 1, 2 or 3 hours. Roles and unavailability narrow each worker's domain, and the
sets saw that only through the cap. ADR 0040 listed sets from each worker's own domain as still open.

Phase 11 step 4 (2026-11-17) looked for a role-aware bound, outside the program first:

* **Groups:** the workers who can fill a group of slots must take that group's load between them, by a price per
  group (water-filling, and whole slots). They never pruned: in the relaxed solution, every group already got enough.
* **A price per slot** (the ceiling measured on 2026-11-16): on top of the program, it pruned 18% and 27% of the
  nodes it was asked about on `multiday_05` and seed 3009, but cost 80–100 µs per node.
* **Sets from each worker's own domain:** it gave more than the price per slot, as its multiplier is found exactly:
  3.8 times the progress per node on `multiday_05`, 1.95 on seed 3009, and half the nodes on `sweep_08` and
  `sweep_12`. Asked after the other bounds, from scratch at each node, it cost about 24 µs per node, and the search
  was 2% slower overall. Replacing the global sets, with each worker's counts kept up to date, it was 18% faster.

## Decision

**Each worker's sets $T_w$ come from the unfilled slots in their own domain**, counted per load:

1. **The sets:** whole numbers of the unfilled slots of each load in the worker's domain, no more of each load than
   they're in the domain of. Every completion gives each worker slots from their current domain (forward checking
   only removes workers who can't take a slot), so these sets hold every extra load they could get, and the bound
   stays valid. They lie within the global sets (the slots in a worker's domain carry at most their cap, and number
   at most $\lfloor \mathrm{cap}_w / u \rfloor$), so the bound is never lower than before.
2. **Listing them:** as before, per worker: the combinations of every load but the most frequent, with the most
   frequent load's count chosen next to the ideal, while there are at most `MAX_LOAD_COMBINATIONS` (64)
   combinations; beyond that, for that worker only, the intervals
   $\lbrace 0 \rbrace \cup [u_w, L_w] \cup [2u_w, 2L_w] \cup \dots$ up to the number of slots in their domain, cut at
   their cap ($u_w$ and $L_w$ the smallest and largest load among those slots).
3. **Kept up to date:** the incremental scorer keeps, for each worker, the count of unfilled slots of each load in
   their domain, changed with their cap: when a slot is filled, for every worker in its domain, and when forward
   checking drops a worker from a slot's domain, for that worker; undone exactly. It replaces the count of unfilled
   slots of each load overall, which nothing else used. The bound from scratch counts the same from the domains.
4. **Cached:** a worker's sets depend only on their counts per load, so they're built once per set of counts and kept
   (`COMBINATIONS_CACHE_SIZE`, 4096 sets of counts at a time).

The multiplier is found by tangents as before ([ADR 0044](0044-best-whole-slot-multiplier-by-tangents.md)); the
rounding margin, where the bound doesn't apply, and the cheap water-filling bound checked first are unchanged.

## Consequences

* **The same results:** a higher valid bound only prunes more of what can't beat the pocket.
  * Tests: never above brute force's best whole-slot completion on random cases (exact and interval sets, powers 2
    and 3), equal to a long multiplier search, and a case by hand where the global sets were below the best
    completion and these reach it; the incremental bound equals the one from scratch.
  * On every benchmark input, alone and as day 2, on CPython and PyPy, the schedules are identical to the recorded
    ones (2026-11-17).
* **Faster where roles or availability narrow the domains, slower where they don't** (2026-11-17, the program's code
  against `dev`'s with ADRs 0044 and 0045; one process, four searches at a time, two rounds):
  * PyPy, 16 inputs searched to the end: 301 s to 281 s and 302 s to 273 s (6–10% less). `sweep_12` 37–46% less,
    `sweep_08` 21–38%, `sweep_09` 22–25%, `confirm_01` 21% (with 0.47, 0.50, 0.82 and 0.67 of the nodes); `sweep_06`
    35–38% more, `sweep_07` 13%, `sweep_10` 10%, where it prunes little or nothing.
  * PyPy, 48-hour inputs up to 20 million nodes, progress per second: `multiday_05` 60–71 times, seed 3009 3.5–3.9,
    `multiday_04` 0.91–0.92.
  * `multiday_05` searched to the end with 12 processes: 689 s for the first period and 230 s for the second, against
    3107 s and 505 s in the laptop baseline of 2026-11-16 (before ADRs 0044–0046), with the same schedules.
  * CPython, 6 small inputs: 119 s to 104 s (13% less).
  * With 12 processes, the 15 benchmark inputs: on PyPy, 51 s to 48 s alone and 40 s to 43 s as day 2; on CPython,
    145 s to 96 s alone and 98 s to 87 s as day 2.
* **A setting to turn it off,** where it only costs, and perhaps choosing it from how constrained the input is, are
  deferred ([Future work](../explanation/future-work.md#search-performance)).
* **Not taken:** groups of slots with a price each (never binding), and a price per slot (too costly at every node).
  Making the bookkeeping cheaper (a worker's cache key kept up to date with their counts, and workers who can take
  every unfilled slot sharing one set) is left for step 5.
