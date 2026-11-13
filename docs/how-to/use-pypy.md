# Using PyPy for development runs

> [!NOTE]
> **Implemented.**

[PyPy](https://pypy.org/) is a faster Python interpreter. It runs TinyScheg's search about 3 times faster than
CPython, with exactly the same results, so it's the runner for development runs: the tests, the benchmark, the audit
and tuning ([ADR 0033](../decisions/0033-pypy-for-development-runs.md)). CPython (the `tinyscheg` Conda environment,
see [Development setup](development-setup.md)) stays the reference.

## Setting up

From the repository root, with the `tinyscheg` environment activated:

```bash
python tools/setup_pypy.py
```

This downloads the pinned PyPy release for your platform (Linux, Windows or macOS) from pypy.org, checks it against
its published checksum, unpacks it into `.pypy/` (ignored by git, about 200 MB) and installs the libraries the program
and the tests need, at pinned versions. Nothing is installed anywhere else; deleting `.pypy/` removes it.

To set it up again from scratch, for example after the pinned versions change:

```bash
python tools/setup_pypy.py --force
```

## Running code with PyPy

Use `.pypy/bin/pypy3` (on Windows, `.pypy\pypy3.exe`) where you'd use `python`:

```bash
.pypy/bin/pypy3 -m pytest
.pypy/bin/pypy3 src/main.py exampleInput.yml
PYTHONPATH=src .pypy/bin/pypy3 tools/tune.py ...
```

Short runs gain less than long ones: PyPy's just-in-time compiler needs a few seconds to warm up, so a search that
takes a second under CPython may take about as long under PyPy.

## Keeping the code PyPy-compatible

* **Python 3.11 at most.** PyPy implements Python 3.11, so code mustn't use newer syntax or standard library
  features. Running the tests under both interpreters catches it:
  ```bash
  python -m pytest && .pypy/bin/pypy3 -m pytest
  ```
* **The same results on both.** Lists of floats in the scoring are added with `math.fsum` or a plain loop, never
  `sum()`, whose rounding differs between CPython 3.12+ and PyPy; otherwise ties can be broken differently.
* **Close files explicitly** (`with open(...)`). PyPy closes a file only when its garbage collector gets to it, so
  data written to a file that isn't closed can be lost or overwritten.

## Updating PyPy or a library

The PyPy version, each platform's archive checksum (from <https://pypy.org/checksums.html>) and the libraries'
versions are constants at the top of `tools/setup_pypy.py`. Change them there, then run it with `--force`.
