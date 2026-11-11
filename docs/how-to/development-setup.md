# Development setup

> [!NOTE]
> **Implemented.**

## Requirements

* [Conda](https://docs.conda.io/) (Miniconda, Miniforge or Anaconda)
* Git

## Setting up

1. Clone the repository and enter it:
   ```bash
   git clone <repository-url>
   cd TinyScheg
   ```
2. Create the Conda environment from `environment.yml`. This installs Python 3.13 and the project's dependencies:
   ```bash
   conda env create -f environment.yml
   ```
3. Activate the environment:
   ```bash
   conda activate tinyscheg
   ```

## Running code

With the environment activated, run scripts with plain `python` from the repository root:

```bash
python src/main.py exampleInput.yml
```

This writes `exampleInput_schedule.csv` next to the input; see [Command line](../reference/command-line.md) for the
options.

The code is the `tinyscheg` package in `src/tinyscheg/` (see
[Architecture](../explanation/architecture.md#code-layout)), and modules import each other by full package path
(e.g. `from tinyscheg.timing.datetime_range import DateTimeRange`). Running `src/main.py` puts `src/` on the import
path automatically. For anything else, such as `python -c` or an interactive session, set `PYTHONPATH`:

```bash
PYTHONPATH=src python -c "from tinyscheg.timing.datetime_range import DateTimeRange"
```

## Running the tests

Tests live in `tests/` and use pytest. With the environment activated, run them from the repository root:

```bash
python -m pytest
```

`pyproject.toml` puts `src/` and `tools/` (the development tools the tests share, such as the independent
hard-constraint checker) on pytest's import path, so no `PYTHONPATH` is needed.

## Updating dependencies

Dependencies are listed in `environment.yml`. After changing it, update the environment with:

```bash
conda env update -f environment.yml --prune
```

## Viewing the docs

The docs are plain Markdown in `docs/` and can be read directly on GitHub. They can also be viewed as a website,
built with [MkDocs](https://www.mkdocs.org/) and the [Material](https://squidfunk.github.io/mkdocs-material/) theme
(both installed by `environment.yml`).

To browse the docs locally, run from the repository root:

```bash
mkdocs serve
```

and open <http://127.0.0.1:8000>. The site reloads automatically whenever a file in `docs/` or `mkdocs.yml` changes.

To check the docs for broken links and other problems, build them in strict mode, which turns warnings into errors:

```bash
mkdocs build --strict
```

The built site goes into `site/`, which is ignored by git.

When adding a page, also add it to `nav` in `mkdocs.yml`. Write docs so they render correctly both on GitHub and
on the site: link to other pages with relative links, and link to files outside `docs/` (such as source files) with
full GitHub URLs.
