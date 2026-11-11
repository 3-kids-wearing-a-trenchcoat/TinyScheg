# Auditing a schedule

> [!NOTE]
> **Implemented**, and covered by tests (`tests/test_audit.py`, `tests/test_audit_sample.py`).

The [schedule audit](../explanation/schedule-audit.md) is a development tool that judges a schedule from each worker's
point of view. These steps assume the `tinyscheg` environment is activated, from the repository root (see
[Development setup](development-setup.md)). The tools live in `tools/`, outside the `tinyscheg` package, so `src/`
has to be put on the import path with `PYTHONPATH=src`.

## Audit one schedule

1. Write a schedule as CSV:
   ```bash
   python src/main.py exampleInput.yml -o schedule.csv
   ```
2. Audit it against the same input:
   ```bash
   PYTHONPATH=src python tools/audit.py exampleInput.yml schedule.csv
   ```

The report has a card per worker, then the group summary. A card looks like this:

```
Jill: 4 shifts, 14 h; available 48 h
  2025-01-01: 2 shifts, 7 h; available 24 h
  2025-01-02: 2 shifts, 7 h; available 24 h
  2025-01-03: 0 shifts, 0 h; available 0 h
  rests: 10 h, 7 h, 7 h
  short straws: 2 (short rest 2, heaviest day 0, disliked partner 0)
  partners: Jeff ×1, Gilgamesh ×1; with someone they like: 0, with someone they dislike: 0
  complaints:
    - [3] load overall: 4 shifts (14 h), against Siduri's 0 (0 h); unavoidable
    - [1] load on 2025-01-01: 2 shifts (7 h), against Siduri's 0 (0 h); avoidable: giving Siduri front gate 2025-01-01 07:00–10:00 instead of Jack
```

Each complaint starts with its severity in brackets, and ends with whether a single harmless move or swap would fix
it, and which. The summary gives the number of complaints, the avoidable and unavoidable severity, how many workers
have complaints, and the concentration: the most aggrieved worker's share of all severity.

The audit exits with 1 if the schedule breaks a hard constraint (listing the violations), and with 2 if the files
can't be read or don't match each other.

## Compare the audit with the internal penalty

```bash
PYTHONPATH=src python tools/audit_sample.py exampleInput.yml -n 30
```

This samples 30 schedules (20 by default) by shuffling the workers' order before the search, and lists each, best
penalty first, with its audit summary. It ends with the rank correlation between the penalty and the avoidable
severity, and the **disagreements**: schedules among the best quarter by penalty with the most avoidable severity,
named by the seed of their shuffle.

The audit's thresholds are named constants at the top of `tools/audit.py`, and the sampler's at the top of
`tools/audit_sample.py`.
