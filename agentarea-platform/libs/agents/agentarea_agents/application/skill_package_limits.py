"""Limits every skill package write and read goes through.

Package paths become object-store keys under ``skills/{workspace}/{skill}/``.
A ``..`` segment there names a key outside the package -- another
workspace's skill -- on any store that normalises dot segments, so a path is
refused unless it is a plain relative path. An upload is inflated in memory
entry by entry, so its declared sizes are checked before anything is read.
"""

from __future__ import annotations

import zipfile
from pathlib import PurePosixPath

MAX_PACKAGE_FILES = 1000
MAX_PACKAGE_FILE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_TOTAL_BYTES = 50 * 1024 * 1024


def safe_package_path(path: str) -> str:
    """Return ``path`` as a plain relative package path, else raise ``ValueError``.

    A leading ``/`` is dropped: callers address files relative to the package.
    """
    path = path.lstrip("/")
    if not path or "\\" in path or "\x00" in path:
        raise ValueError(f"Invalid skill file path: {path!r}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Invalid skill file path: {path!r}")
    return str(PurePosixPath(*parts))


def check_zip_budget(zf: zipfile.ZipFile) -> None:
    """Refuse an archive whose declared contents exceed the package limits."""
    files = [info for info in zf.infolist() if not info.is_dir()]
    if len(files) > MAX_PACKAGE_FILES:
        raise ValueError(f"Skill package contains more than {MAX_PACKAGE_FILES} files")
    total = 0
    for info in files:
        if info.file_size > MAX_PACKAGE_FILE_BYTES:
            mb = MAX_PACKAGE_FILE_BYTES // (1024 * 1024)
            raise ValueError(f"Skill package file {info.filename!r} is larger than {mb} MB")
        total += info.file_size
    if total > MAX_PACKAGE_TOTAL_BYTES:
        mb = MAX_PACKAGE_TOTAL_BYTES // (1024 * 1024)
        raise ValueError(f"Skill package is larger than {mb} MB uncompressed")


def read_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read one entry, refusing one that inflates past what it declared."""
    with zf.open(info) as handle:
        data = handle.read(MAX_PACKAGE_FILE_BYTES + 1)
    if len(data) > MAX_PACKAGE_FILE_BYTES:
        mb = MAX_PACKAGE_FILE_BYTES // (1024 * 1024)
        raise ValueError(f"Skill package file {info.filename!r} is larger than {mb} MB")
    return data
