# TinyScheg

TinyScheg is a shift scheduler. Given a group of workers, a set of posts that need to be manned and a time period,
it builds a shift schedule that:

* satisfies every **hard constraint** — worker availability, required roles, and a minimum rest period between
  shifts;
* is as **fair** as possible — workload is spread evenly and rest periods aren't needlessly short;
* respects **personal preferences** — who each worker likes or dislikes sharing a shift with.

Scheduling is modelled as a constraint satisfaction problem (CSP) and solved with a backtracking search, combined
with a penalty score that is used to prune the search and pick the best schedule found.

## Status

> [!WARNING]
> **Work in progress.** TinyScheg runs end to end and writes the fairest schedule that meets every hard
> constraint, but slowly: a 24-hour schedule takes a minute or two, and longer ones much more. See the
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

Without `-o`, the schedule is written next to the input as `<input name>_schedule.csv`. See
[Command line](docs/reference/command-line.md) for details.

Input is a YAML file describing the schedule settings, workers and posts. [`exampleInput.yml`](exampleInput.yml)
is an annotated example, and the format is described in [Input format](docs/reference/input-format.md).

## Documentation

All documentation lives in [`docs/`](docs/index.md).

## License

TinyScheg is released under the [MIT License](LICENSE).
