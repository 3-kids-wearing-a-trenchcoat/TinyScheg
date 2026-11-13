"""
Set up the project's PyPy (ADR 0033): download the pinned PyPy release for this platform from pypy.org, check it
against its published checksum, unpack it into .pypy/ at the repository root (ignored by git) and install the pinned
libraries into it. Development runs (the tests, the benchmark, the audit) can then use .pypy/bin/pypy3, about 3 times
faster than CPython with exactly the same results (see docs/how-to/use-pypy.md).
Usage: python tools/setup_pypy.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass

PYPY_VERSION = "7.3.23"   # the PyPy release, implementing Python 3.11
PYTHON_VERSION = "3.11"
DOWNLOAD_URL = "https://downloads.python.org/pypy/{archive}"

# The libraries the program and its tests need, at the versions of the tinyscheg conda environment
REQUIREMENTS = ("pyyaml==6.0.3", "openpyxl==3.1.5", "odfpy==1.4.1", "pytest==9.0.3")

REPOSITORY = pathlib.Path(__file__).resolve().parent.parent
TARGET = REPOSITORY / ".pypy"
DOWNLOAD_CHUNK = 1 << 20  # bytes read at a time while downloading and hashing

EXIT_SUCCESS = 0
EXIT_FAILURE = 1


@dataclass(frozen=True, slots=True)
class Build:
    """One platform's PyPy build: its name in the archive's file name, and the archive's published SHA-256."""
    name: str
    sha256: str

    @property
    def archive(self) -> str:
        """The archive's file name, e.g. 'pypy3.11-v7.3.23-linux64.tar.bz2'."""
        extension = "zip" if self.name.startswith("win") else "tar.bz2"
        return f"pypy{PYTHON_VERSION}-v{PYPY_VERSION}-{self.name}.{extension}"


# The builds by (platform.system(), platform.machine()), with the checksums published at https://pypy.org/checksums.html
BUILDS = {
    ("Linux", "x86_64"): Build("linux64", "16f9f56e82d1f4ec95a324c1a8cacfd78afc7f0656c0a809a18725ef4391453a"),
    ("Linux", "aarch64"): Build("aarch64", "5433ac0ad526aeb35025ef8509bed65cd62ea35cb9e21ac649c69a5eff4eecb6"),
    ("Windows", "AMD64"): Build("win64", "948b8ea58dea5b9917210fe4afd242c788fbfaba1c3f1a25e696a404f703389a"),
    ("Darwin", "arm64"): Build("macos_arm64", "4747b3aceba4c1c6104cddc0fe5ea302101d32955f0957347b9ecc4fbd7aed05"),
    ("Darwin", "x86_64"): Build("macos_x86_64", "c95363c4e87235d11a6cec8128239c291b1eb67a752778fbcfe029a71da82b5e"),
}


class SetupError(Exception):
    """Setting up PyPy failed, for a reason the message explains."""


def choose_build(system: str, machine: str) -> Build:
    """
    The PyPy build for a platform
    :param system: str, as platform.system() gives it
    :param machine: str, as platform.machine() gives it
    :return: the Build
    """
    build = BUILDS.get((system, machine))
    if build is None:
        supported = ", ".join(f"{s} {m}" for s, m in BUILDS)
        raise SetupError(f"no PyPy build is set up for {system} {machine} (supported: {supported})")
    return build


def interpreter_path(target: pathlib.Path, system: str) -> pathlib.Path:
    """Where the PyPy interpreter is in an unpacked build: bin/pypy3, or pypy3.exe at the top on Windows."""
    return target / "pypy3.exe" if system == "Windows" else target / "bin" / "pypy3"


def file_sha256(path: pathlib.Path) -> str:
    """A file's SHA-256, in hex."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(DOWNLOAD_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: pathlib.Path, expected: str) -> None:
    """Raise SetupError unless the file's SHA-256 is the expected one."""
    actual = file_sha256(path)
    if actual != expected:
        raise SetupError(f"{path.name} has SHA-256 {actual}, but {expected} was published: not using it")


def download(url: str, destination: pathlib.Path) -> None:
    """Download a URL to a file."""
    with urllib.request.urlopen(url) as response, destination.open("wb") as file:
        shutil.copyfileobj(response, file, DOWNLOAD_CHUNK)


def unpack(archive: pathlib.Path, target: pathlib.Path) -> None:
    """
    Unpack a PyPy archive into target, without the archive's single top-level folder
    :param archive: pathlib.Path, a .tar.bz2 or .zip whose contents are all in one top-level folder
    :param target: pathlib.Path, which must not exist yet
    """
    with tempfile.TemporaryDirectory(dir=target.parent) as staging:
        staging_path = pathlib.Path(staging)
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(staging_path)
        else:
            with tarfile.open(archive, "r:bz2") as tarred:
                tarred.extractall(staging_path, filter="tar")  # keeps the interpreter's permissions and links
        top = list(staging_path.iterdir())
        if len(top) != 1 or not top[0].is_dir():
            raise SetupError(f"{archive.name} doesn't hold a single top-level folder")
        top[0].rename(target)


def install_requirements(interpreter: pathlib.Path) -> None:
    """Install pip into the PyPy, then the pinned libraries."""
    subprocess.run([str(interpreter), "-m", "ensurepip"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(interpreter), "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
                    *REQUIREMENTS], check=True)


def set_up(target: pathlib.Path, force: bool) -> pathlib.Path:
    """
    Set up PyPy in target
    :param target: pathlib.Path, the folder to put it in
    :param force: bool, True to replace an existing one
    :return: the path of the interpreter
    """
    system = platform.system()
    build = choose_build(system, platform.machine())
    if target.exists():
        if not force:
            raise SetupError(f"{target} already exists; run with --force to replace it")
        shutil.rmtree(target)
    with tempfile.TemporaryDirectory() as downloads:
        archive = pathlib.Path(downloads) / build.archive
        print(f"downloading {build.archive} ...")
        download(DOWNLOAD_URL.format(archive=build.archive), archive)
        verify_checksum(archive, build.sha256)
        print("checksum verified; unpacking ...")
        unpack(archive, target)
    interpreter = interpreter_path(target, system)
    print(f"installing {', '.join(REQUIREMENTS)} ...")
    install_requirements(interpreter)
    return interpreter


def main(argv: list[str] | None = None) -> int:
    """Set up PyPy; print where it is, or why it failed."""
    parser = argparse.ArgumentParser(description="Set up the project's PyPy in .pypy/ (ADR 0033).")
    parser.add_argument("--force", action="store_true", help="replace an existing .pypy/")
    arguments = parser.parse_args(argv)
    try:
        interpreter = set_up(TARGET, arguments.force)
    except (SetupError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILURE
    print(f"done: {interpreter.relative_to(REPOSITORY)}")
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
