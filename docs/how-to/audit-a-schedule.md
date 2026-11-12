# Auditing a schedule

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_audit.py`, `tests/test_audit_sample.py`).

The [schedule audit](../explanation/schedule-audit.md) is a development tool that judges a schedule from each worker's
point of view. These steps assume the `tinyscheg` environment is activated, from the repository root (see
[Development setup](development-setup.md)). The tools live in `tools/`, outside the `tinyscheg` package, so `src/`
has to be put on the import path with `PYTHONPATH=src`.

## Audit one schedule

1. Write a schedule (as CSV here; XLSX and ODS work the same):
   ```bash
   python src/main.py exampleInput.yml -o schedule.csv
   ```
   This finds the best schedule, which takes about 10 seconds (see [Command line](../reference/command-line.md)).
2. Audit it against the same input:
   ```bash
   PYTHONPATH=src python tools/audit.py exampleInput.yml schedule.csv
   ```

The report has a card per worker, then the group summary. A card looks like this (one complaint left out):

```
Gilgamesh: 3 shifts, 8 h; available 24 h
  2025-01-01: 3 shifts, 8 h; available 24 h
  rests: 7 h, 9 h
  short straws: 0 (short rest 0, disliked partner 0)
  partners: Enkidu ×2; with someone they like: 2, with someone they dislike: 0
  complaints:
    - [1] load on 2025-01-01: 3 shifts (8 h), against Jill's 1 (4 h); easy fix: giving Jack front gate 2025-01-01 22:00–2025-01-02 00:00 instead of Gilgamesh
```

Each complaint starts with its severity in brackets, and ends with its [easy fix](../explanation/schedule-audit.md#easy-fixes),
a chain of up to three harmless moves and swaps, if one was found. The summary gives the number of complaints and
how many have an easy fix, the severity with and without one, how many workers have complaints, and the
concentration: the most aggrieved worker's share of all severity.

An audit of the example takes well under a second.

The audit exits with 1 if the schedule breaks a hard constraint (listing the violations), and with 2 if the files
can't be read or don't match each other.

## Compare the audit with the internal penalty

```bash
PYTHONPATH=src python tools/audit_sample.py exampleInput.yml -n 30
```

This samples 30 schedules (20 by default) by shuffling the workers' order before the search, and lists each, best
penalty first, with its audit summary. It ends with the rank correlations between the penalty and the severity with
an easy fix, and between the penalty and the total severity, and the **disagreements**: schedules among the best
quarter by penalty with the most severity with an easy fix, named by the seed of their shuffle. 30 samples of
the example take about 5 seconds.

The audit's thresholds are named constants at the top of `tools/audit.py`, and the sampler's at the top of
`tools/audit_sample.py`.
