# TinyScheg

TinyScheg is a shift scheduler. Given a group of workers, a set of posts that need to be manned and a time period,
it builds the fairest shift schedule it can prove exists, one that:

* satisfies every **hard constraint** — worker availability, required roles, and a minimum rest period between
  shifts;
* is as **fair** as possible — work is shared in proportion to each worker's availability, and rest periods aren't
  needlessly short;
* respects **personal preferences** — who each worker likes or dislikes sharing a shift with.

## Example

The annotated [`exampleInput.yml`](exampleInput.yml) describes nine workers, their roles, when they're unavailable and
whom they like or dislike working with, and two posts over one day:

```yaml
settings:
  time: ["2025-01-01", "2025-01-02"]
  min_rest: 6
workers:
  - name: "Jack"
    roles: ["supervisor", "other"]
    unavailable:
      - ["2025-01-01T04:00:00", "2025-01-01T06:00:00"]
    likes: ["Jill"]
  # ...
```

`python src/main.py exampleInput.yml -o schedule.csv` finds the best schedule in a couple of seconds and proves
that no better one exists:

```text
penalty 20.26 (likes 3.52, workload 32.65, rest 0.87), the best possible
```

| time (Jan 1)  | front gate         | desk    |
|---------------|--------------------|---------|
| 00:00–03:00   | Ninsun & Jill      |         |
| 03:00–06:00   | Gilgamesh & Siduri |         |
| 06:00–07:00   | Enkidu & Shamhat   |         |
| 07:00–08:00   | Jeff               |         |
| 08:00–10:00   | Jeff               | Jack    |
| 10:00–12:00   | Anne               | Jack    |
| 12:00–13:00   | Anne               | Jill    |
| 13:00–16:00   | Ninsun             | Jill    |
| 16:00–19:00   | Siduri             | Shamhat |
| 19:00–20:00   | Enkidu & Gilgamesh | Shamhat |
| 20:00–22:00   | Enkidu & Gilgamesh |         |
| 22:00–00:00   | Jeff & Anne        |         |

The schedule can be written as CSV, Excel (`.xlsx`) or OpenDocument (`.ods`).

## How it works

* **Constraint satisfaction with branch and bound.** Scheduling is modelled as a constraint satisfaction problem
  and solved by backtracking search with forward checking. A penalty score that never decreases along the search,
  together with lower bounds on what the rest of a schedule must still cost, prunes partial schedules that can't
  beat the best one found, so the schedule returned is the best possible, not just a good one
  ([search algorithm](docs/explanation/search-algorithm.md), [scoring](docs/explanation/scoring.md)).
* **A fairness model.** Workload is judged against each worker's availability, short rests cost more the shorter
  they are, and likes and dislikes are weighed against each other, each as a separate part of the penalty.
* **Schedules that follow on.** A new schedule takes the previous one into account (who worked late, who rested),
  and TinyScheg warns when the next period with the same settings couldn't be filled at all.
* **Parallel search with the same result.** The search splits across processes, about 7.6 times faster on 8 cores,
  and always returns exactly the schedule a single process would ([ADR 0041](docs/decisions/0041-parallel-search-with-the-sequential-result.md)).

The design is documented in full: the [docs](docs/index.md) follow the [Diátaxis](https://diataxis.fr/)
structure, with every design decision recorded in an [Architecture Decision Record](docs/decisions/README.md)
(55 so far), and the code is covered by over 750 tests, run on both CPython and PyPy with identical results.

## Status

> [!NOTE]
> **Work in progress.** TinyScheg runs end to end and writes the fairest schedule that meets every hard
> constraint. A 24-hour schedule takes seconds to minutes; longer ones can take much more. See the
> [roadmap](docs/roadmap.md) for what's next, and [the docs](docs/index.md) for the status of each component.

## Getting started

TinyScheg uses a [Conda](https://docs.conda.io/) environment:

```bash
conda env create -f environment.yml
conda activate tinyscheg
```

See [Development setup](docs/how-to/development-setup.md) for details.

To create a schedule, run from the repository root:

```bash
python src/main.py exampleInput.yml -o schedule.csv
```

The output file's extension chooses the format: `.csv`, `.xlsx` (Excel) or `.ods` (LibreOffice and other
OpenDocument spreadsheets). Without `-o`, the schedule is written next to the input as `<input name>_schedule.csv`. Run
`python src/main.py --help` for every option, and see [Command line](docs/reference/command-line.md) for details.

Input is a YAML file describing the schedule settings, workers and posts. [`exampleInput.yml`](exampleInput.yml)
is an annotated example, and the format is described in [Input format](docs/reference/input-format.md).

## Documentation

The documentation is published at **[3-kids-wearing-a-trenchcoat.github.io/TinyScheg](https://3-kids-wearing-a-trenchcoat.github.io/TinyScheg/)**,
with navigation and search; its source lives in [`docs/`](docs/index.md), which also reads well on GitHub.

## License

TinyScheg is released under the [MIT License](LICENSE).
