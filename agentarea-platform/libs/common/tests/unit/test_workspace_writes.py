"""Where a manual write may land in workspace storage.

The REST upload and the MCP upload tool both resolve paths through these
helpers, so a path one surface refuses is refused by the other.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentarea_common.artifacts import WorkspaceConflictError, WorkspaceValidationError
from agentarea_common.artifacts.workspace_writes import (
    ensure_writable_file,
    is_reserved_path,
    plan_uploads,
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


class PlanningStore(FakeStore):
    """Store stand-in for ``plan_uploads``: digests of existing files, signed PUTs."""

    def __init__(self, digests: dict[str, str] | None = None, **kwargs) -> None:
        super().__init__(files=set(digests or {}), **kwargs)
        self.digests = digests or {}
        self.authorized: list[str] = []

    async def head(self, workspace_id: str, path: str):
        if path not in self.digests:
            return None
        return {"size": 1, "content_type": "text/markdown", "sha256": self.digests[path]}

    async def authorize_put(self, workspace_id, path, *, sha256_hex, content_type=None):
        if len(sha256_hex) != 64:
            raise ValueError("sha256 must be a 64-character lowercase hex digest")
        self.authorized.append(path)
        return SimpleNamespace(
            url=f"https://store.example/{path}", headers={"h": "v"}, expires_in=600
        )


SHA_A = "a" * 64
SHA_B = "b" * 64


@pytest.mark.asyncio
async def test_a_file_already_stored_with_the_same_digest_is_skipped() -> None:
    store = PlanningStore(digests={"wiki/index.md": SHA_A})

    plan = await plan_uploads(store, "ws-1", [{"path": "wiki/index.md", "sha256": SHA_A}])

    assert plan == [{"path": "wiki/index.md", "status": "unchanged"}]
    assert store.authorized == []


@pytest.mark.asyncio
async def test_a_changed_or_new_file_gets_a_presigned_put() -> None:
    store = PlanningStore(digests={"wiki/index.md": SHA_A})

    plan = await plan_uploads(
        store,
        "ws-1",
        [{"path": "wiki/index.md", "sha256": SHA_B}, {"path": "wiki/new.md", "sha256": SHA_A}],
    )

    assert [(p["path"], p["status"]) for p in plan] == [
        ("wiki/index.md", "upload"),
        ("wiki/new.md", "upload"),
    ]
    assert plan[1] == {
        "path": "wiki/new.md",
        "status": "upload",
        "upload_url": "https://store.example/wiki/new.md",
        "method": "PUT",
        "headers": {"h": "v"},
        "expires_in": 600,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry",
    [
        "wiki/index.md",
        {"sha256": SHA_A},
        {"path": "../escape.md", "sha256": SHA_A},
        {"path": "tasks/t/out.md", "sha256": SHA_A},
        {"path": "wiki/x.md", "sha256": "nope"},
    ],
)
async def test_an_entry_that_cannot_be_written_is_reported_on_its_own(entry) -> None:
    store = PlanningStore()

    plan = await plan_uploads(store, "ws-1", [entry, {"path": "ok.md", "sha256": SHA_A}])

    assert plan[0]["status"] == "error"
    assert plan[0]["error"]
    assert plan[1]["status"] == "upload"
    assert store.authorized == ["ok.md"]
