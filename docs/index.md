# TinyScheg documentation

TinyScheg is a shift scheduler that assigns workers to shifts while satisfying hard constraints (availability,
roles, minimum rest), keeping the schedule fair and respecting workers' preferences.
It models scheduling as a constraint satisfaction problem (CSP) and searches for the best schedule using a penalty
score that never decreases along the search, allowing hopeless partial schedules to be pruned early.

> [!WARNING]
> TinyScheg is a **work in progress** and does not run end-to-end yet.
> Code described as implemented exists but **has not been tested**, and an audit on 2026-11-10 found bugs in all of
> it. The code is being rebuilt bottom-up, module by module with tests, starting with a walking skeleton: parse the
> input, generate slots, search for the first legal schedule and write it as CSV. Scoring and branch and bound come
> after that.

## How these docs are organized

The docs follow the [Diátaxis](https://diataxis.fr/) framework, with design decisions recorded as
Architecture Decision Records (ADRs).

* **How-to guides** — steps for accomplishing a specific task.
  * [Development setup](how-to/development-setup.md)
* **Reference** — exact technical descriptions of formats and code.
  * [Input format](reference/input-format.md)
  * [Output format](reference/output-format.md)
  * API: [`DateTimeRange`](reference/api/datetime-range.md) · [`Worker`](reference/api/worker.md) ·
    [`Post` and `Slot`](reference/api/post-and-slot.md)
* **Explanation** — how TinyScheg works and why.
  * [Architecture](explanation/architecture.md)
  * [Domain model](explanation/domain-model.md)
  * [CSP formulation](explanation/csp-formulation.md)
  * [Search algorithm](explanation/search-algorithm.md)
  * [Scoring](explanation/scoring.md)
  * [Glossary](explanation/glossary.md)
  * [Future work](explanation/future-work.md)
* **[Decisions](decisions/README.md)** — the design decisions made so far and the reasoning behind them.

Tutorials will be added once TinyScheg runs end-to-end.

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
| `DateTimeRange`                     | Implemented (known bugs)  |
| `Worker`                            | Partially implemented     |
| `Post`                              | Partially implemented     |
| `Slot` (domain, constraints, MRV)   | Partially implemented     |
| Shift generation (segments)         | Not yet implemented       |
| Input parsing and validation        | Not yet implemented       |
| Search (backtracking, pocket)       | Not yet implemented       |
| Undo (change records)               | Not yet implemented       |
| Scoring                             | Not yet implemented       |
| Output (CSV grid)                   | Not yet implemented       |
| Output (XLSX, ODS)                  | Not yet implemented       |
| Command-line interface              | Not yet implemented       |
