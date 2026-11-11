# Command line

Source: [`src/tinyscheg/cli.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/src/tinyscheg/cli.py)

> [!IMPORTANT]
> **Partially implemented.** Everything on this page works, but the schedule written is the **first** legal schedule
> found, not yet the fairest one: scoring and branch and bound aren't implemented yet (see the
> [Roadmap](../roadmap.md)).

## Usage

From the repository root, with the `tinyscheg` environment activated
(see [Development setup](../how-to/development-setup.md)):

```bash
python src/main.py INPUT [-o OUTPUT]
```

* `INPUT` — the YAML input file (see [Input format](input-format.md)).
* `-o OUTPUT`, `--output OUTPUT` — the schedule file to write. Its extension sets the format (see
  [Output format](output-format.md)); currently only `.csv` is supported, in any case. If omitted, the schedule is
  written next to the input, named after it: `shifts/week1.yml` → `shifts/week1_schedule.csv`.

An existing file at the output path is replaced, but only once a schedule has been found: if anything goes wrong, no
file is written and an existing one is left as it was.

On success, two lines are printed: what was written, and the schedule's
[penalty](../explanation/scoring.md) — lower is better — with its three parts before weighting, e.g.:

```
wrote exampleInput_schedule.csv: 34 shifts, 47 slots, 9 workers
penalty 4.36 (likes 3.69, workload 5.03, rest 3.71)
```

The penalty and each part lie between 0 and the number of workers, shown to `PENALTY_DECIMALS` (2) decimals. Until
branch and bound is built, the schedule is the first legal one found, so the penalty shows how fair it happens to be
rather than the best achievable.

## Errors

Every problem is reported on standard error, prefixed with `tinyscheg:`, and nothing is written.

* **Unsupported output format** — checked before anything else, so a long search doesn't end in a typo:
  `unsupported output format ".txt" (supported: .csv)`.
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
      This is where the search found out, not necessarily the cause, which may be a slot or two later.
* **Interrupted** (Ctrl+C) — `interrupted; no schedule written`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | A schedule was written. |
| 1    | The input is valid, but no legal schedule exists. |
| 2    | Invalid arguments or input, or the input or output file couldn't be read or written. |
| 130  | Interrupted with Ctrl+C. |
