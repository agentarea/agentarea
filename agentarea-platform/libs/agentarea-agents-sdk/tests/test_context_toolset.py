"""Tests for the read-only org-context toolset (tier 1 = org store).

The context toolset lets an agent READ the organization's durable context store
(ArtifactService, workspace-scoped). It must be read-only: no save/put/delete.
It is distinct from the task-workspace file tools (tier 2) on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agentarea_agents_sdk.tools.context_toolset import ContextToolset


@dataclass
class _Obj:
    path: str
    size: int = 0
    content_type: str | None = None


class _FakeOrgStore:
    """Minimal StorageClient-compatible fake for the org context store."""

    def __init__(self, data: dict[tuple[str, str], bytes]):
        self._data = data

    async def get(self, workspace_id: str, path: str) -> tuple[bytes, str | None]:
        try:
            return self._data[(workspace_id, path)], "text/plain"
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    async def list(self, workspace_id: str, prefix: str = "") -> list[_Obj]:
        return [
            _Obj(path=path)
            for (ws, path) in self._data
            if ws == workspace_id and path.startswith(prefix)
        ]

    async def exists(self, workspace_id: str, path: str) -> bool:
        return (workspace_id, path) in self._data


@pytest.mark.asyncio
async def test_read_context_returns_bytes_decoded():
    store = _FakeOrgStore({("ws1", "shared/notes.md"): b"hello org"})
    ct = ContextToolset(storage=store, workspace_id="ws1")
    result = await ct.read_org_file("shared/notes.md")
    assert result == "hello org"


@pytest.mark.asyncio
async def test_list_context_returns_paths():
    store = _FakeOrgStore(
        {
            ("ws1", "shared/a.md"): b"a",
            ("ws1", "projects/b.md"): b"b",
            ("ws2", "other.md"): b"x",
        }
    )
    ct = ContextToolset(storage=store, workspace_id="ws1")
    result = await ct.list_org_files()
    assert "shared/a.md" in result
    assert "projects/b.md" in result
    # cross-workspace isolation: ws2 content never appears
    assert "other.md" not in result


@pytest.mark.asyncio
async def test_read_context_missing_file_is_graceful_error():
    store = _FakeOrgStore({})
    ct = ContextToolset(storage=store, workspace_id="ws1")
    result = await ct.read_org_file("nope.md")
    assert "does not exist" in result.lower() or "error" in result.lower()


@pytest.mark.asyncio
async def test_read_context_rejects_path_traversal():
    store = _FakeOrgStore({("ws1", "shared/notes.md"): b"secret"})
    ct = ContextToolset(storage=store, workspace_id="ws1")
    for bad in ("../secret", "/etc/passwd", "a/../../b"):
        result = await ct.read_org_file(bad)
        assert "escapes" in result.lower() or "error" in result.lower()


def test_context_toolset_is_read_only():
    ct = ContextToolset(workspace_id="ws1")
    method_names = set(ct._tool_methods.keys())
    # only read surface is exposed
    assert method_names == {"read_org_file", "list_org_files"}
    for forbidden in ("save_org_file", "write_org_file", "put", "delete", "save_file"):
        assert forbidden not in method_names
