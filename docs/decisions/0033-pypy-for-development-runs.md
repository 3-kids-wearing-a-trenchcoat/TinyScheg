# 0033. PyPy for development runs; the code stays Python 3.11-compatible

**Status:** Accepted.

## Context

The search takes most of the time of every development run (the tests' search cases, the benchmark, the audit,
tuning), and most of a search is spent proving that nothing beats the best schedule found, so it can't be cut by
finding a good schedule sooner. Profiled on 2026-11-13, the time per node is spread thinly over the search's
bookkeeping and the incremental scores, with no single hotspot left.

Running the same search faster was measured on 2026-11-13, on the example and the 15 benchmark inputs (3 rounds,
per-input medians), every run giving exactly the same nodes, penalties and schedules as CPython:

| Setup | Total | Speedup |
|---|---|---|
| CPython 3.13 | 509 s | 1.00x |
| CPython 3.13, compiled with mypyc (csp and scoring) | 218 s | 2.34x |
| PyPy 3.11 | 156 s | 3.27x |

(Both with the cheaper per-node bookkeeping committed the same day.) PyPy runs the code and its libraries unchanged.
mypyc needed small type-annotation edits, a C compiler and a build step, and compiling the model as well broke input
validation. Results only became identical across interpreters once the scoring added lists of floats with
`math.fsum` or plain loops instead of `sum()`, whose rounding changed in CPython 3.12.

conda-forge's PyPy stops at Python 3.9, which the code can't run on (it uses `@dataclass(slots=True)`, 3.10+), so
PyPy comes from pypy.org's official builds, which are portable folders that need no installation.

For the final distribution, the user wants something a non-technical person can run by clicking one obvious file,
with nothing to install (2026-11-13). A folder holding a portable PyPy, the code and a launcher is one way to do
that; since PyPy's builds are ready-made for each platform and the libraries are pure Python, building one needs no
compiling.

## Decision

1. **PyPy is the runner for development runs**: the tests, the benchmark, the audit and tuning. CPython 3.13 stays
   the reference: the code must give exactly the same results on both, and the tests are run under both.
2. **The code stays compatible with Python 3.11**, the version PyPy implements: no syntax or standard library
   features newer than 3.11.
3. **The project's PyPy is set up by `tools/setup_pypy.py`**, into `.pypy/` at the repository root (ignored by
   git): it downloads a pinned PyPy release for the platform from pypy.org, checks it against its published
   checksum, and installs the libraries at pinned versions. Everyone gets the same PyPy, and the same steps can later
   fill a distribution's folder.
4. **For distribution, a folder with a portable PyPy is the leading option**, to be confirmed when it's built: the
   graphical interface's toolkit, once chosen, must work on PyPy.

Rejected:

* **mypyc** for development runs: slower than PyPy, and a build step after every change. It stays an option for a
  CPython distribution.
* **Downgrading the project to Python 3.11**: CPython 3.13 is supported two years longer, and nothing is gained;
  keeping the code 3.11-compatible is enough.
* **Installing PyPy outside the repository** (e.g. under `~/.local/opt`): it wouldn't be pinned or rebuildable from
  the repository, nor rehearse a distribution.

## Consequences

* Development runs are about 3 times faster (3.5-3.8x on the longest benchmark inputs); short runs gain less, since
  PyPy's just-in-time compiler needs time to warm up.
* Two interpreters to keep working, and a compatibility limit on the language: code using 3.12+ features fails
  under PyPy, which running the tests under both catches.
* PyPy closes files only when its garbage collector runs, not as soon as they're no longer used: files must be
  closed explicitly (`with open(...)`), or written data can be lost or overwritten.
* Updating PyPy or a library means changing the pinned versions and checksums in `tools/setup_pypy.py` and running
  it with `--force`.
