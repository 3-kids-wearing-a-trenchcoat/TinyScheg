# Future work

Ideas and features that have been discussed and deliberately **deferred**. Nothing on this page is implemented or
decided; each item would get its own ADR when it's taken up. Items are listed in priority order.

When and in what order items are taken up is in the [Roadmap](../roadmap.md); each item deferred here is also listed
in its "Later" section.

## Schedule history

> [!WARNING]
> **Not yet implemented.** Highest priority.

Currently every run creates a **new** schedule, in which every worker is "fresh". When schedules are created for
consecutive periods (typically 24–48 hours), this causes two problems at the boundary between periods:

* **Rest:** a worker who took the last shift of the previous schedule could be given the first shift of the new one,
  breaking the minimum rest period.
* **Fairness:** workload and rest fairness start over every period, so small imbalances can accumulate across
  schedules.

The planned solution is to accept a **previously generated schedule** as additional input. Its assignments are
treated as **fixed** and included in scoring, so the algorithm effectively *extends* the existing schedule rather
than starting from scratch. The previous schedule is read from TinyScheg's own
[output](../reference/output-format.md#reading-the-output-back), which is designed for this.

## Explaining infeasibility

> [!WARNING]
> **Not yet implemented.**

When no legal schedule exists, TinyScheg reports that and produces no output (see
[ADR 0011](../decisions/0011-no-output-for-infeasible-inputs.md)). It would help to also say **why**. Cheap checks
before the search can catch many causes, e.g. a slot whose domain is empty right after availability and role
pruning ("no worker with the supervisor role is available on 2025-01-02 04:00–07:00").

Reporting the slots no worker can fill, and the point at which the search ran out of options, is decided
([ADR 0020](../decisions/0020-report-where-infeasibility-was-found.md)). What remains here is a fuller explanation:
further cheap checks (e.g. a shift needing more distinct workers than its slots' domains hold together), or a
minimal set of conflicting requirements.

## Search performance

> [!WARNING]
> **Not yet implemented.** Deferred until TinyScheg works end to end; performance isn't a concern at the intended
> schedule sizes yet. With MRV ordering, finding a first legal schedule is instant at these sizes (decided
> 2026-11-11); the ideas below are to be reconsidered once branch and bound can be measured.

* **Cheapest-first value ordering.** Try the worker whose assignment adds the least penalty first. This doesn't
  change the result: as [ADR 0003](../decisions/0003-variable-ordering-mrv-degree.md) argues, the best schedule is
  found regardless of value order, and least-constraining-value ordering is of no use when every solution is
  considered. But with branch and bound, *how much* is pruned depends on how good the pocket schedule is when each
  partial schedule is reached. Finding a good schedule early therefore prunes more. The ordering depends on the
  slot and the current state, so `Worker` still needs no CSP-related ordering.
* **Symmetry breaking.** Slots of the same shift that require the same role are interchangeable: assigning
  (Anne, Bob) or (Bob, Anne) to them yields the same schedule, so the search explores $k!$ equivalent branches for
  $k$ identical slots. Requiring workers to be assigned to identical slots in a fixed order removes the duplicates.
* **A stronger lower bound.** The pocket comparison uses the penalty accumulated so far, which is a weak bound,
  especially for workload, which barely grows until late in the search. Since every slot must be filled, the
  remaining hours are known; by the same Jensen argument used in [Scoring](scoring.md#the-function-varphi-and-jensens-inequality),
  spreading them so that every workload is equal gives a lower bound on the remaining workload penalty that can be added
  before comparing.
* **Time limit.** Stop the search after a given time and return the best pocket schedule found so far. Note that
  with a time limit, value ordering affects the *result* and not just the speed.

## Incremental scoring

> [!WARNING]
> **Not yet implemented.**

Penalties are first computed from scratch for every state. Updating them incrementally would be faster, but must
stay exactly path-independent (see [ADR 0012](../decisions/0012-deterministic-path-independent-scoring.md)), for
example by using exact arithmetic. The from-scratch computation then serves as a test oracle.

## Dangling shifts

> [!WARNING]
> **Not decided.** Deferred until TinyScheg works end to end.

When a segment's length isn't a multiple of the shift length, its last shift is cut short
([ADR 0018](../decisions/0018-slot-generation-by-segments.md)). This is expected to be rare in real use. Options if it
needs handling: keep the short shift (current behaviour), merge it into the previous shift, or let the input set a
minimum shift length. If the segment scheme itself doesn't work well in practice, it will be revisited.

## Time and post preferences

> [!WARNING]
> **Not yet implemented.** Low priority.

Workers' preferences currently concern only other workers (likes and dislikes). They could be extended to
preferences about *when* or *where* they work, e.g. avoiding mornings or preferring a particular post. These would
be additional, monotone penalty components.

## Spreadsheet presentation

> [!WARNING]
> **Not yet implemented.** Low priority.

* **Right-to-left sheets.** XLSX and ODS sheets can be displayed right to left, as rosters in Hebrew and other
  right-to-left languages usually are, e.g. through an input setting. Output is left to right for now.
* **Roles in the output.** The grid doesn't show which worker fills which role. Cells could show it, e.g.
  `Jack (security)`.

## Schedule audit

> [!WARNING]
> **Not yet implemented.** Low priority; deferred 2026-11-11.

* **Samples with no easy fix at all.** In one sample of the example (seed 16 of `tools/audit_sample.py`), none of
  its 74 complaints had an easy fix, though most samples have many. Worth finding out why: whether the greedy chain
  search misses fixes there, or the schedule really has none.

## Documentation

> [!WARNING]
> **Not yet implemented.** Low priority.

* **Tutorials**, once TinyScheg runs end to end.
* **A generated API reference** (e.g. mkdocstrings), replacing the hand-written pages in `docs/reference/api/`.
* **Publishing the docs site**, e.g. to GitHub Pages.

## Accessibility for non-technical users

> [!WARNING]
> **Not yet implemented.** Lowest priority: these are for once TinyScheg is finished and working, to make it usable
> by people who don't work with the command line.

* **An optional graphical interface.** A GUI for people put off by the command line, alongside the command-line
  interface rather than replacing it.
* **Simple distribution.** A single executable file per platform that needs no installation of Python or other
  dependencies, and can be used either from the command line or through the GUI. Windows and Linux versions, and
  possibly a macOS version.
