# Command line

Source: [`src/tinyscheg/cli.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/cli.py)

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_cli.py`).

## Usage

From the repository root, with the `tinyscheg` environment activated
(see [Development setup](../how-to/development-setup.md)):

```bash
python src/main.py INPUT [-o OUTPUT]
```

* `INPUT` — the YAML input file (see [Input format](input-format.md)).
* `-o OUTPUT`, `--output OUTPUT` — the schedule file to write. Its extension sets the format (see
  [Output format](output-format.md)); `.csv`, `.xlsx` and `.ods` are supported, in any case. If omitted, the schedule is
  written next to the input, named after it: `shifts/week1.yml` → `shifts/week1_schedule.csv`.

An existing file at the output path is replaced, but only once a schedule has been found: if anything goes wrong, no
file is written and an existing one is left as it was.

The schedule written is the **best** legal one: the one with the lowest
[penalty](../explanation/scoring.md), found by [branch and bound](../explanation/search-algorithm.md#branch-and-bound-the-pocket).
The search runs to the end, with no limit, which can take a while: about 10 seconds for the 24-hour
`exampleInput.yml`, and much longer for longer schedules. Its progress is shown as it goes (below), and Ctrl+C stops
it, writing the best schedule found so far ([Stopping early](#stopping-early-ctrlc)).

If the input has a [history](input-format.md#history), workers of a previous schedule who are no longer in the input
are named in a warning on standard error first (`tinyscheg: warning: ...`); the run goes on.

While it runs, its progress is shown on standard error
([ADR 0035](../decisions/0035-search-progress-and-keeping-the-best-on-interrupt.md)). On a terminal, it's a block of
two lines redrawn in place: the best schedule found so far, and how far the search has got:

```
best:     penalty 8.38 (likes 2.00, workload 32.77, rest 0.92), found after 0:04
progress: 37.2% finished, 1,423,912 nodes, 0:07 elapsed, about 0:11 left (rough)
```

* **Finished** is the share of the search space the search has finished: each partial schedule's share is split
  equally among the workers tried for its next slot, and a branch's share counts once the branch is searched to the
  end or pruned. It only rises, reaches 100% when the search ends, and can jump when a large branch is pruned.
* **Time left** is the time elapsed times the share left over the share finished, shown once `ESTIMATE_MIN_FINISHED`
  (1%) is finished. It's rough: the most promising workers are tried first, so the early branches take longest and
  the later ones are pruned fast, and the estimate starts high and improves as the run goes on.
* The block is redrawn at most every `REDRAW_SECONDS` (0.25 s), each line cut to the terminal's width. When the
  search ends, it stays as last drawn, ending in `done` (or `interrupted`), and the summary follows. Where the
  terminal doesn't understand the codes for redrawing several lines, one line is redrawn instead, the progress
  first: `37.2% finished, 1,423,912 nodes, 0:07 elapsed, about 0:11 left (rough) | best 8.38 after 0:04`.

When standard error isn't a terminal (redirected to a file, say), each better schedule found is reported on a line
of its own, with the seconds since the search started, and a progress line every `PLAIN_PROGRESS_SECONDS` (60 s):

```
tinyscheg: found penalty 8.79 after 0 s
tinyscheg: found penalty 8.53 after 1 s
tinyscheg: found penalty 8.38 after 4 s
tinyscheg: 81.3% of the search finished after 60 s, 9,118,208 nodes, about 14 s left (rough)
```

The best schedule is often found long before the search ends: the rest of the time goes into making sure nothing
beats it. When it ends, two lines are printed on standard output: what was written, and the schedule's penalty —
lower is better — with its three parts before weighting, e.g.:

```
wrote exampleInput_schedule.csv: 12 shifts, 17 slots, 9 workers
penalty 8.38 (likes 2.00, workload 32.77, rest 0.92), the best possible
```

The penalty and each part are at least 0, each part in its own units ([Scoring](../explanation/scoring.md)); only
differences between schedules mean anything. They're shown to `PENALTY_DECIMALS` (2) decimals; the
seconds in plain progress lines to `ELAPSED_DECIMALS` (0), and the share finished to `PERCENT_DECIMALS` (1).

With a [history](input-format.md#history), the schedule is searched as the continuation of the previous ones
([ADR 0031](../decisions/0031-history-as-the-filled-part-of-one-schedule.md)): the file written holds the new period
only, and the counts are the new period's, but the penalty is that of the whole schedule, history included, so it
isn't comparable with a run without one.

### Stopping early (Ctrl+C)

Ctrl+C stops the search. If it has found a schedule by then, the best one found so far is written as usual, and the
summary says that it isn't proven the best, and how much of the search was finished:

```
wrote exampleInput_schedule.csv: 12 shifts, 17 slots, 9 workers
penalty 8.38 (likes 2.00, workload 32.77, rest 0.92), the best found before the search was interrupted, not proven the best (37.2% of the search finished)
```

The exit code is still 130, so a script can tell that the run didn't finish. If no schedule has been found yet,
nothing is written: `interrupted before any schedule was found; no schedule written`.

## Errors

Every problem is reported on standard error, prefixed with `tinyscheg:`, and nothing is written.

* **Unsupported output format** — checked before anything else, so a long search doesn't end in a typo:
  `unsupported output format ".txt" (supported: .csv, .xlsx, .ods)`.
* **Missing or unreadable input file** — `can't read week1.yml: No such file or directory`.
* **Invalid input** — every problem found, each naming where it is (see [Input format](input-format.md#errors)).
* **No legal schedule** ([ADR 0011](../decisions/0011-no-output-for-infeasible-inputs.md),
  [ADR 0020](../decisions/0020-report-where-infeasibility-was-found.md)), described by what was encountered:
    * slots no worker can fill, found before the search, all listed:
      ```
      tinyscheg: no legal schedule exists:
        - no worker can fill desk, 2025-01-02 08:00–12:00 (role "supervisor")
      ```
    * otherwise, how far the search got and the slot it was stuck on:
      ```
      tinyscheg: no legal schedule exists; the search filled at most 2 of 4 slots, and got stuck at gate, 2025-01-01 04:00–08:00 (role "any")
      ```
      This is where the search found out, not necessarily the cause, which may be a slot or two later. The search
      fills the most constrained slots first, so it usually gets stuck early, at or near the bottleneck.
* **Interrupted** (Ctrl+C) before the search, or before it found any schedule — `interrupted; no schedule written`,
  or `interrupted before any schedule was found; no schedule written`. Interrupted after it found one, the best
  schedule found so far is written ([Stopping early](#stopping-early-ctrlc)).

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | A schedule was written. |
| 1    | The input is valid, but no legal schedule exists. |
| 2    | Invalid arguments or input, or the input or output file couldn't be read or written. |
| 130  | Interrupted with Ctrl+C: the best schedule found so far was written, if the search had found one. |
