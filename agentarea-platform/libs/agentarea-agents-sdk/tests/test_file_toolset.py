from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from agentarea_agents_sdk.tools.file_toolset import FileToolset


@dataclass
class _Object:
    path: str
    size: int
    content_type: str


class _Repository:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str, str], tuple[bytes, str]] = {}

    async def put(self, workspace_id, task_id, path, data, content_type=None, **kwargs):
        self.files[(workspace_id, task_id, path)] = (data, content_type)
        return _Object(path, len(data), content_type)

    async def get(self, workspace_id, task_id, path):
        key = (workspace_id, task_id, path)
        if key not in self.files:
            raise FileNotFoundError(path)
        return self.files[key]

    async def exists(self, workspace_id, task_id, path):
        return (workspace_id, task_id, path) in self.files

    async def list(self, workspace_id, task_id, prefix="", max_items=10_000):
        return [
            _Object(path, len(value[0]), value[1])
            for (ws, task, path), value in self.files.items()
            if ws == workspace_id and task == task_id and path.startswith(prefix)
        ][:max_items]

    async def delete(self, workspace_id, task_id, path, **kwargs):
        del self.files[(workspace_id, task_id, path)]


@pytest.mark.asyncio
async def test_file_toolset_uses_task_manifest_namespace_and_preserves_nested_path():
    repository = _Repository()
    tool = FileToolset(
        workspace_repository=repository,
        workspace_id="ws",
        task_id="task",
    )

    assert await tool.save_file("print('ok')", "src/nested/a.py") == "src/nested/a.py"
    assert await tool.read_file("src/nested/a.py") == "print('ok')"
    listed = json.loads(await tool.list_files())
    assert listed["files"] == ["src/nested/a.py"]
    assert ("ws", "task", "src/nested/a.py") in repository.files


@pytest.mark.asyncio
async def test_file_toolset_rejects_absolute_and_traversal_paths():
    tool = FileToolset(
        workspace_repository=_Repository(),
        workspace_id="ws",
        task_id="task",
    )
    assert "escapes workspace" in await tool.save_file("x", "/tmp/x")
    assert "escapes workspace" in await tool.save_file("x", "../x")


import pytest as _pytest
from agentarea_agents_sdk.tools.file_toolset import FileToolset as _FT


@_pytest.mark.asyncio
async def test_save_file_rejects_binary_extensions():
    tool = _FT(workspace_id="ws")
    for name in ("deck.pptx", "model.xlsx", "spec.docx", "chart.png", "out.pdf"):
        msg = await tool.save_file("whatever", name)
        assert "text only" in msg and "shell" in msg, f"{name}: {msg}"


@_pytest.mark.asyncio
async def test_save_file_still_accepts_text():
    tool = _FT(workspace_id="ws")
    assert await tool.save_file("hello", "notes.md") == "notes.md"
    assert await tool.save_file("x,y", "data.csv") == "data.csv"
