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
python src/main.py
```

Modules in `src/` import each other by bare module name (e.g. `from DateTimeRange import DateTimeRange`).
Running a script that lives in `src/` puts `src/` on the import path automatically. For anything else, such as
`python -c` or an interactive session, either run from within `src/` or set `PYTHONPATH`:

```bash
PYTHONPATH=src python -c "from DateTimeRange import DateTimeRange"
```

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
