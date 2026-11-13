"""Tests for tools/setup_pypy.py (no network: downloading isn't tested here)."""
import hashlib
import io
import pathlib
import tarfile
import zipfile

import pytest

from setup_pypy import (BUILDS, Build, SetupError, choose_build, interpreter_path, unpack, verify_checksum)


def test_every_supported_platform_has_a_build() -> None:
    assert choose_build("Linux", "x86_64").archive == "pypy3.11-v7.3.23-linux64.tar.bz2"
    assert choose_build("Windows", "AMD64").archive == "pypy3.11-v7.3.23-win64.zip"
    assert all(len(build.sha256) == 64 for build in BUILDS.values())


def test_an_unsupported_platform_is_refused() -> None:
    with pytest.raises(SetupError, match="no PyPy build"):
        choose_build("Linux", "riscv64")


def test_the_interpreter_is_in_bin_except_on_windows(tmp_path: pathlib.Path) -> None:
    assert interpreter_path(tmp_path, "Linux") == tmp_path / "bin" / "pypy3"
    assert interpreter_path(tmp_path, "Windows") == tmp_path / "pypy3.exe"


def test_a_wrong_checksum_is_refused(tmp_path: pathlib.Path) -> None:
    archive = tmp_path / "archive"
    archive.write_bytes(b"contents")
    verify_checksum(archive, hashlib.sha256(b"contents").hexdigest())
    with pytest.raises(SetupError, match="not using it"):
        verify_checksum(archive, hashlib.sha256(b"other").hexdigest())


def _tar_bz2(path: pathlib.Path, files: dict[str, bytes]) -> None:
    """Write a .tar.bz2 holding the files."""
    with tarfile.open(path, "w:bz2") as tarred:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tarred.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize("extension", ["tar.bz2", "zip"])
def test_unpacking_drops_the_top_level_folder(tmp_path: pathlib.Path, extension: str) -> None:
    files = {"pypy-build/bin/pypy3": b"interpreter", "pypy-build/lib/module.py": b"code"}
    archive = tmp_path / f"build.{extension}"
    if extension == "zip":
        with zipfile.ZipFile(archive, "w") as zipped:
            for name, data in files.items():
                zipped.writestr(name, data)
    else:
        _tar_bz2(archive, files)
    target = tmp_path / ".pypy"
    unpack(archive, target)
    assert (target / "bin" / "pypy3").read_bytes() == b"interpreter"
    assert (target / "lib" / "module.py").read_bytes() == b"code"


def test_an_archive_without_a_single_top_level_folder_is_refused(tmp_path: pathlib.Path) -> None:
    archive = tmp_path / "build.tar.bz2"
    _tar_bz2(archive, {"one/file": b"a", "two/file": b"b"})
    with pytest.raises(SetupError, match="single top-level folder"):
        unpack(archive, tmp_path / ".pypy")
    assert not (tmp_path / ".pypy").exists()
    assert Build("win64", "0" * 64).archive.endswith(".zip")
