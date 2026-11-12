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
`exampleInput.yml`, and much longer for longer schedules. Ctrl+C stops it (see [Errors](#errors)).

If the input has a [history](input-format.md#history), workers of a previous schedule who are no longer in the input
are named in a warning on standard error first (`tinyscheg: warning: ...`); the run goes on.

While it runs, each better schedule found is reported on standard error, with the time since the search started, so
that a long run can be seen to be working:

```
tinyscheg: found penalty 3.48 after 0 s
tinyscheg: found penalty 2.25 after 0 s
tinyscheg: found penalty 2.22 after 2 s
tinyscheg: found penalty 2.18 after 12 s
tinyscheg: found penalty 2.16 after 14 s
```

The best schedule is often found long before the search ends: the rest of the time goes into making sure nothing
beats it. When it ends, two lines are printed on standard output: what was written, and the schedule's penalty —
lower is better — with its three parts before weighting, e.g.:

```
wrote exampleInput_schedule.csv: 12 shifts, 17 slots, 9 workers
penalty 2.16 (likes 1.80, workload 3.32, rest 0.22), the best possible
```

The penalty and each part lie between 0 and the number of workers, shown to `PENALTY_DECIMALS` (2) decimals; the
seconds in progress lines to `ELAPSED_DECIMALS` (0).

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
* **Interrupted** (Ctrl+C) — `interrupted; no schedule written`. Interrupting a search discards it, including the
  best schedule found so far.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | A schedule was written. |
| 1    | The input is valid, but no legal schedule exists. |
| 2    | Invalid arguments or input, or the input or output file couldn't be read or written. |
| 130  | Interrupted with Ctrl+C. |
