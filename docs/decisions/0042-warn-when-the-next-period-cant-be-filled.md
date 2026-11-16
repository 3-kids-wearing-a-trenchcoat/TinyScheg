# 0042. Warn when a schedule leaves the next period no legal schedule

**Status:** Accepted.

## Context

The search finds the best schedule for its own period, with no regard for the period after it
([Future work](../explanation/future-work.md#a-schedule-that-leaves-the-next-one-with-no-legal-schedule)). A first
period starts with every worker rested, which the next one doesn't, and nothing tells the search that work in its
last hours limits who can start the next. On the benchmark (2026-11-14), some first periods left the next one no
legal schedule at all: in real use, a schedule after which the next one can't be made.

Three ways to deal with it were considered: warning the scheduler, avoiding it in the search, or leaving it to the
scheduler. The user chose to **warn**, "so long as it's computationally cheap" (2026-11-15), with the next period
assumed to have **exactly the same parameters**: for a period that isn't whole days, **the same hours, a whole number
of days later** (2026-11-16). That's also how the tuning continues its benchmark inputs, which removed a flaw: a
16-hour period from 16:00 to 08:00 was continued from 08:00 to midnight, a different schedule, with no legal schedule
even with every worker rested.

Measured before deciding (2026-11-15/16):
* **Cheap:** on 7 benchmark inputs, checking that every slot of the next period has someone took 4–7 ms, and a search
  for any legal schedule (not the best) needed 1–23 nodes, catching every real case.
* **But not always:** proving that there's no legal schedule can take very long. On one 48-hour input, the search
  hadn't decided after 5 minutes.

## Decision

**After writing a schedule, the command line checks the next period and warns on standard error if it can't be
filled** (`csp/next_period.py`).

1. **The next period** (`next_period_input`): the same input, starting the first whole number of days
   (`NEXT_PERIOD_STEP`) after this period's start that isn't before its end; each worker's unavailability repeated as
   much later; this period's schedule added at the end of the history. Right after a period of 24 or 48 hours; the
   next day at the same time after a 16-hour one.
2. **The check** (`check_next_period`): first the slots no worker can fill, then a search for any legal schedule,
   with this schedule as history.
3. **A limit in nodes, not time:** the search stops after about `NEXT_PERIOD_CHECK_NODES` (500,000) nodes, about
   3 seconds on CPython at worst and well under one on PyPy. A node limit gives the same answer on every machine, and
   needs no timer (the development tools' timer doesn't exist on Windows). It's checked where the search already
   reports its progress, every few thousand nodes, so the search's own steps don't change.
4. **Three answers:**
   * **fillable:** nothing is printed;
   * **not fillable:** `warning: after this schedule, the next period with the same parameters (2025-01-02
     00:00–2025-01-03 00:00) has no legal schedule`;
   * **undecided** (the limit reached): a note that the check couldn't tell.
5. **The schedule doesn't change**, nor the exit code. The warning comes after the summary, and also after a schedule
   written when the search was interrupted.
6. **One definition:** the tuning's second period (`tools/tune.py`) uses `next_period_input` too.

## Consequences

* **The scheduler is told** when the next schedule can't be made, while there's still time to add workers or change
  the schedule by hand. It's a warning about the next period as it would be with the same parameters; the real next
  period may differ, for better (more workers) or worse (more unavailability).
* **The example warns.** `exampleInput.yml`'s best schedule uses the security holders the front gate needs at night
  at the end of the day, so the next day's night can't be filled (2026-11-16); both days planned as one schedule could
  be. On the benchmark, at the defaults, `sweep_08` warns.
* **A worse next period, not an impossible one, isn't warned about:** a first period can leave the next a worse
  schedule than another first period would. That stays open
  ([Future work](../explanation/future-work.md#a-schedule-that-leaves-the-next-one-with-no-legal-schedule)).
* **`find_first_schedule` gained an optional node limit**; a search stopped by it returns no schedule, marked as not
  complete.
