# 0043. By default, one search process per physical core

**Status:** Accepted. Amends [ADR 0041](0041-parallel-search-with-the-sequential-result.md) (point 5).

## Context

The parallel search ([ADR 0041](0041-parallel-search-with-the-sequential-result.md)) runs, unless told otherwise
(`--jobs`), one process per processor the operating system reports, `os.cpu_count()`. With two threads per core,
that's two processes per core. On the machine it was measured on (a desktop with 8 cores and 16 threads), the
second thread of each core gained little and cost nothing: 7.6 times faster than one process with 8 processes, 7.9
with 16.

Development then moved to a laptop (2026-11-16; [Future work](../explanation/future-work.md#speeds-on-the-two-machines-2026-11-16)):
12 cores, 24 threads. There, `confirm_01` took about 25 s with 12 or 16 processes and about 35 s with 24, the
default: a third slower, held back by heat, its processor at its 95 °C limit with any number of processes. Many of
the people TinyScheg is for will be on laptops.

The standard library counts only logical processors. Counting physical cores without a library takes different code
on each operating system, two of which (Windows, macOS) can't be tested here; halving the logical count is wrong on
processors without two threads per core, which would then use half their cores. The user approved adding `psutil`
(2026-11-16), which counts physical cores on Windows, Linux and macOS, and works on PyPy.

## Decision

**By default, the search runs one process per physical core:** `psutil.cpu_count(logical=False)`, or, if it can't
tell, `os.cpu_count()` as before (`default_processes`). `--jobs` still sets any number, and the schedule is the same
whatever the number (ADR 0041).

## Consequences

* **On the laptop,** the default is 12 processes instead of 24: about a third faster on the measured input.
* **On a desktop like the first one,** it would be 8 instead of 16: about 4% slower (7.6 against 7.9 times one
  process), within the run-to-run variation.
* **A new dependency,** `psutil`, in `environment.yml` and in the PyPy setup (`tools/setup_pypy.py`). It's compiled,
  unlike the other libraries, but packaging tools handle it, which matters for
  [distribution](../explanation/future-work.md#accessibility-for-non-technical-users).
* **Untested ground:** the right number on Windows and macOS, and with spawned processes there, is still to be
  measured before distribution (ADR 0041).
