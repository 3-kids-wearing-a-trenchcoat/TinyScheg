# TinyScheg documentation

TinyScheg is a shift scheduler that assigns workers to shifts while satisfying hard constraints (availability,
roles, minimum rest), keeping the schedule fair and respecting workers' preferences.
It models scheduling as a constraint satisfaction problem (CSP) and searches for the best schedule using a penalty
score that never decreases along the search, allowing hopeless partial schedules to be pruned early.

> [!WARNING]
> TinyScheg is a **work in progress**. It runs end to end and writes the fairest schedule that meets every hard
> constraint, but slowly: a 24-hour schedule takes seconds to minutes, and longer ones much more. The original code,
> in which an audit on 2026-11-10 found bugs throughout, has been rebuilt bottom-up, module by module with tests;
> every component in the [status table](#implementation-status) is now covered by them. See the
> [Roadmap](roadmap.md).

## Roadmap

What's left to do, and in what order, is in the [Roadmap](roadmap.md).

## How these docs are organized

The docs follow the [Diátaxis](https://diataxis.fr/) framework, with design decisions recorded as
Architecture Decision Records (ADRs).

* **How-to guides** — steps for accomplishing a specific task.
  * [Development setup](how-to/development-setup.md)
  * [Auditing a schedule](how-to/audit-a-schedule.md) (development tool)
  * [Using PyPy for development runs](how-to/use-pypy.md)
* **Reference** — exact technical descriptions of formats and code.
  * [Input format](reference/input-format.md)
  * [Output format](reference/output-format.md)
  * [Command line](reference/command-line.md)
  * API: [`DateTimeRange`](reference/api/datetime-range.md) · [`Worker`](reference/api/worker.md) ·
    [`DailyWindow`](reference/api/daily-window.md) · [`Post`, `Shift` and `Slot`](reference/api/post-and-slot.md) ·
    [`ScheduleInput`](reference/api/schedule-input.md) · [`parsing`](reference/api/parsing.md) ·
    [`Problem`](reference/api/problem.md) · [search](reference/api/search.md) ·
    [`output`](reference/api/output.md) · [`scoring`](reference/api/scoring.md)
* **Explanation** — how TinyScheg works and why.
  * [Architecture](explanation/architecture.md)
  * [Domain model](explanation/domain-model.md)
  * [CSP formulation](explanation/csp-formulation.md)
  * [Search algorithm](explanation/search-algorithm.md)
  * [Scoring](explanation/scoring.md)
  * [Schedule audit](explanation/schedule-audit.md) (development tool)
  * [Tuning the scoring](explanation/tuning.md) (how the default parameters are chosen)
  * [Glossary](explanation/glossary.md)
  * [Future work](explanation/future-work.md)
* **[Decisions](decisions/README.md)** — the design decisions made so far and the reasoning behind them.

There are no tutorials yet ([future work](explanation/future-work.md#documentation)).

## Implementation status

Sections describing behaviour are marked with their implementation status:

> [!NOTE]
> **Implemented.** The behaviour described exists in code.

> [!IMPORTANT]
> **Partially implemented.** Some of the behaviour described exists in code; the note says what's missing.

> [!WARNING]
> **Not yet implemented.** This describes planned behaviour that doesn't exist in code yet.

The docs describe **intended** behaviour. Where existing code doesn't match it, that's a bug.

| Component                           | Status                    |
|-------------------------------------|---------------------------|
| `DateTimeRange`                     | Implemented and tested    |
| `Worker`                            | Implemented and tested    |
| `Post`                              | Implemented and tested    |
| `Shift` and `Slot`                  | Implemented and tested    |
| Shift generation (segments)         | Implemented and tested    |
| Domains and constraints (CSP setup) | Implemented and tested    |
| `DailyWindow`                       | Implemented and tested    |
| Input parsing and validation        | Implemented and tested    |
| Search (backtracking, ordering)     | Implemented and tested    |
| Branch and bound (pocket)           | Implemented and tested    |
| Parallel search                     | Implemented and tested    |
| Search progress, Ctrl+C keeps best  | Implemented and tested    |
| Undo (change records)               | Implemented and tested    |
| Scoring parameters and constants    | Implemented and tested    |
| Scoring penalties                   | Implemented and tested    |
| Output (CSV grid)                   | Implemented and tested    |
| Output (XLSX, ODS)                  | Implemented and tested    |
| Command-line interface              | Implemented and tested    |
| Schedule history                    | Implemented and tested    |
| Schedule audit (development tool)   | Implemented and tested    |
