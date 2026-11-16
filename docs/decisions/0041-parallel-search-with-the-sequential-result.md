# 0041. Branch and bound in parallel processes, with exactly the sequential result

**Status:** Accepted, amended by [0043](0043-one-process-per-physical-core.md).

## Context

Branch and bound ([ADR 0004](0004-branch-and-bound-with-monotone-penalty.md)) ran in one process, on one of the
machine's processors. The user asked (2026-11-15) whether running it in parallel could make it faster, on two
conditions:
* **more work explored mustn't outweigh the gain**, since a process can't prune on a schedule another hasn't found
  yet;
* **the result mustn't change.**

Three facts shaped the answer:
* **Python runs one thread at a time.** CPython and PyPy both have a global interpreter lock, so CPU-bound threads
  take turns on one processor. Parallel search needs separate processes, with only a little shared between them.
* **Most of the search is proving, not finding.** The best schedule is usually found early (`confirm_01`: at 15 s of
  a 4-minute search). The rest of the work, proving nothing beats it, doesn't depend on the order branches are visited
  in, so processes can share it without waste.
* **Today's result depends on order.** Of equally good schedules, the search keeps the first found
  ([ADR 0017](0017-plain-forward-checking-and-pruning-on-ties.md),
  [ADR 0024](0024-cheapest-first-value-order-and-workload-bound.md)). Processes keeping whichever they happen to find
  first would make the schedule depend on timing.

Measured before building it (2026-11-15; archived outside the repository):
* **The work splits evenly.** Cut into a few hundred subtrees, in the search's own order, the largest subtree was
  1-2% of the work and cutting cost nothing.
* **A prototype ran close to the ideal.** Run one input at a time on a quiet machine with 8 cores and 16 threads, it
  was 7.6 times faster with 8 processes and 7.9 with 16, across the example and the 15 benchmark inputs.
* **No extra work.** The processes together visited within 4% of the sequential search's nodes on every input over
  1.5 s, including the one whose best comes late.
* **Results identical in every run:** 208 timed runs, and 120 more with random delays injected into the processes.

## Decision

**The search runs in several processes (`csp/parallel.py`), with exactly the sequential search's result.**

1. **Cutting.** The tree is cut at the first depth giving at least `SUBTREES_PER_PROCESS` (32) subtrees per process.
   * **Numbering:** subtrees are numbered in the order the sequential search would visit them. The tree's shape (the
     slot chosen and the workers' order at every node) doesn't depend on the pocket, so the numbering is fixed.
   * **Leaves above the cut:** a complete schedule above the cut depth is a subtree of its own.
   * **Same incremental totals:** each subtree is reached by replaying its path's assignments in the same order, so
     the incremental totals, and the order workers are tried in below, are bit-identical to the sequential search's.
2. **Sharing.** A pool of processes takes the subtrees from a queue, in order. They share the best schedule found so
   far, with the number of the subtree it came from, under one lock:
   * **Pruning:** subtree *i* prunes a branch whose bound is above the best's penalty, or at least the best's penalty
     when *i* comes at or after the best's subtree *j*. An earlier subtree may still tie, and the sequential search
     would have kept its schedule.
   * **Replacing the best:** a complete schedule replaces the best if its penalty is lower, or equal and from an
     earlier subtree.
   * **Reading:** each process reads the shared best into a copy every `SHARE_INTERVAL_NODES` (4096) nodes. A stale
     copy is never ahead of the shared one, so it only prunes less.
3. **Merging.** Each subtree's best (its first found, among equals) is merged by lowest (penalty, subtree).
4. **Progress, new bests and Ctrl+C** ([ADR 0035](0035-search-progress-and-keeping-the-best-on-interrupt.md)).
   * **Shares:** each subtree carries its share of the search space. Each process writes the share it has finished to
     its own slot of a shared table, and the main process adds them up every `POLL_SECONDS` (0.25 s). The total still
     only rises and reaches 1 at the end.
   * **New bests:** the shared best also holds its penalty's parts and its assignment, written only on an
     improvement. The main process reports strictly better ones.
   * **Ctrl+C:** the processes ignore it. The main process sets a shared stop flag, which the processes check with the
     shared best; it lets them finish and keeps the shared best. Processes aren't killed: one killed while holding the
     lock would leave the main process waiting for it forever.
5. **How many processes.** The command line's `--jobs`, by default one per processor the operating system reports
   (`os.cpu_count()`); `--jobs 1` runs the sequential search itself, unchanged. Processes are forked on Linux, so
   they inherit the main process's state, including a warmed-up PyPy compiler, and spawned elsewhere.

**Why the result is the same.** Let *S* be the sequential search's schedule: the first, in the sequential order, of
the schedules with the lowest penalty *P*, in subtree *i*.
* **No earlier tie:** no subtree before *i* has a schedule at *P*, and no schedule before *S* in subtree *i* does.
* **Nothing on S's path is pruned.** Every node on *S*'s path has a bound of at most *P* (the bounds are valid,
  ADR 0024 and [ADR 0040](0040-workload-bound-in-whole-slots.md)). The shared best is always either above *P*, or at
  *P* from a later subtree, so neither rule prunes such a node.
* **So S wins the merge.** Subtree *i* finds *S* and keeps it, and the merge picks it: any other schedule at *P* is
  from a later subtree.

The same goes for an infeasible input's report ([ADR 0020](0020-report-where-infeasibility-was-found.md)): the
deepest point is taken from the first subtree, in order, to reach the greatest depth.

## Consequences

* **The same schedule, sooner.** The checks behind this:
  * **Brute-force inputs, history, infeasible:** tests compare the parallel search with the sequential one on every
    brute-force input (where there's no legal schedule, the same stuck point), and on a schedule with a history.
  * **Timing:** they repeat the comparison with random delays and the shared best read at every node.
  * **Benchmarks:** every benchmark input, alone and as day 2, gives the recorded schedules.
  * **Sequential unchanged:** with one process, the search is unchanged: the same schedules, node counts, progress
    reports and new bests as before, byte for byte, on 37 inputs.
* **Faster** (2026-11-15, prototype, PyPy, one input at a time on 8 cores and 16 threads):

  | Processes | 2 | 4 | 8 | 16 |
  |---|---|---|---|---|
  | All inputs | 2.1x | 4.1x | 7.6x | 7.9x |
  | `confirm_01` (249 s alone) | 2.2x | 4.3x | 8.4x | 9.2x |

  Beyond the physical cores little is gained, but nothing is lost, so the default uses every processor reported.
  Even inputs under a second ran a little faster. On CPython, with the production code and 16 processes, the example
  went from 31 s to 3.5 s, `sweep_09` from 51 s to 5.6 s and `sweep_04` from 97 s to 11 s (8.8-9.2x). With the
  production code on PyPy, `confirm_01` takes 32 s from the command line, against 4-4½ minutes in one process.
* **Node counts vary from run to run.** The processes' timing decides how soon each prunes on the others' finds, so
  the progress line's node counts and timing differ between runs; the schedule never does.
* **Untested ground:**
  * **Spawned processes** (Windows, macOS) load and warm up on their own, a cost that only short runs feel; it should
    be measured there before distribution.
  * **The development tools** (tuning, the audit's sampler) keep the sequential search: they already run many inputs
    at once.
* **What the search module gained:** a cut depth, a replay of a path and two hooks for the pocket's
  comparison; with them unset, it behaves exactly as before.
