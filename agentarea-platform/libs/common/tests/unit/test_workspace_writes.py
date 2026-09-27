"""Where a manual write may land in workspace storage.

The REST upload and the MCP upload tool both resolve paths through these
helpers, so a path one surface refuses is refused by the other.
"""

from __future__ import annotations

import pytest
from agentarea_common.artifacts import WorkspaceConflictError, WorkspaceValidationError
from agentarea_common.artifacts.workspace_writes import (
    ensure_writable_file,
    is_reserved_path,
    resolve_write_path,
)


class FakeStore:
    def __init__(self, files: set[str] = frozenset(), folders: set[str] = frozenset()) -> None:
        self.files = set(files)
        self.folders = set(folders)

    async def exists(self, workspace_id: str, path: str) -> bool:
        return path in self.files

    async def list(self, workspace_id: str, prefix: str = "", max_items: int = 1000):
        return [p for p in self.folders if p.startswith(prefix)][:max_items]


def test_an_explicit_path_keeps_its_directories() -> None:
    assert resolve_write_path("wiki/api/auth.md") == "wiki/api/auth.md"


def test_without_a_path_the_file_lands_at_the_root_under_its_own_name() -> None:
    assert resolve_write_path("", "nested/report.md") == "report.md"


@pytest.mark.parametrize(
    "bad_path", ["../escape.md", "/absolute.md", "wiki/../../etc/passwd", "wiki//double.md"]
)
def test_paths_that_escape_the_workspace_are_refused(bad_path: str) -> None:
    with pytest.raises(WorkspaceValidationError):
        resolve_write_path(bad_path)


@pytest.mark.parametrize("reserved", ["tasks/t-1/out.txt", "staging/x/f.txt", ".trash/old/f.txt"])
def test_reserved_prefixes_cannot_be_written(reserved: str) -> None:
    assert is_reserved_path(reserved)
    with pytest.raises(WorkspaceValidationError):
        resolve_write_path(reserved)


@pytest.mark.asyncio
async def test_a_file_cannot_become_a_parent_folder() -> None:
    store = FakeStore(files={"wiki"})

    with pytest.raises(WorkspaceConflictError):
        await ensure_writable_file(store, "ws-1", "wiki/index.md")


@pytest.mark.asyncio
async def test_a_folder_cannot_be_overwritten_by_a_file() -> None:
    store = FakeStore(folders={"wiki/index.md/child.md"})

    with pytest.raises(WorkspaceConflictError):
        await ensure_writable_file(store, "ws-1", "wiki/index.md")


@pytest.mark.asyncio
async def test_a_fresh_path_is_writable() -> None:
    await ensure_writable_file(FakeStore(), "ws-1", "wiki/index.md")
