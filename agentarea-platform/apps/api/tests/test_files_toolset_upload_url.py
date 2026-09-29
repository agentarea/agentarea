"""The MCP files toolset can write: it hands out presigned PUTs for files.

Before this tool the platform MCP could list, link and delete workspace files
but not create one, so a harness had to fall back to REST with a separate API
key to put anything into storage.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.tools import files_toolset
from agentarea_api.tools.files_toolset import FilesToolset
from agentarea_common.auth.context import UserContext

SHA = "a" * 64


@pytest.fixture(autouse=True)
def caller():
    with use_mcp_user_context(UserContext(user_id="user-1", workspace_id="ws-1")):
        yield


@pytest.fixture
def service(monkeypatch):
    service = SimpleNamespace(
        exists=AsyncMock(return_value=False),
        list=AsyncMock(return_value=[]),
        head=AsyncMock(return_value=None),
        authorize_put=AsyncMock(
            return_value=SimpleNamespace(
                url="https://store.example/put",
                headers={"Content-Type": "text/markdown", "x-amz-checksum-sha256": "qg=="},
                expires_in=3600,
            )
        ),
    )
    built: list[dict] = []

    def build(**kwargs):
        built.append(kwargs)
        return service

    @asynccontextmanager
    async def fake_context():
        yield (None, UserContext(user_id="user-1", workspace_id="ws-1"), None, None, None)

    monkeypatch.setattr(files_toolset, "ArtifactService", build)
    monkeypatch.setattr(files_toolset, "platform_context", fake_context)
    service.built = built
    return service


async def _upload(*entries: dict) -> dict:
    return json.loads(await FilesToolset().upload_urls(files=list(entries)))


@pytest.mark.asyncio
async def test_it_returns_a_presigned_put_for_each_requested_path(service) -> None:
    result = await _upload({"path": "wiki/index.md", "sha256": SHA})

    assert result == {
        "uploads": [
            {
                "path": "wiki/index.md",
                "status": "upload",
                "upload_url": "https://store.example/put",
                "method": "PUT",
                "headers": {"Content-Type": "text/markdown", "x-amz-checksum-sha256": "qg=="},
                "expires_in": 3600,
            }
        ]
    }
    service.authorize_put.assert_awaited_once_with(
        "ws-1", "wiki/index.md", sha256_hex=SHA, content_type=None
    )
    assert service.built[0]["actor"].user_id == "user-1"
    assert service.built[0]["recorder"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_path", ["../escape.md", "tasks/t-1/out.txt", ".trash/x/f.md", ""])
async def test_a_path_outside_the_writable_workspace_is_refused(service, bad_path) -> None:
    result = await _upload({"path": bad_path, "sha256": SHA})

    assert result["uploads"][0]["status"] == "error"
    service.authorize_put.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_file_cannot_become_a_folder(service) -> None:
    service.exists = AsyncMock(side_effect=lambda _ws, path: path == "wiki")

    result = await _upload({"path": "wiki/index.md", "sha256": SHA})

    assert result["uploads"][0]["status"] == "error"
    service.authorize_put.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_bad_entry_does_not_block_the_rest(service) -> None:
    result = await _upload(
        {"path": "../escape.md", "sha256": SHA},
        {"path": "wiki/index.md", "sha256": SHA},
    )

    assert [(r["status"], r["path"]) for r in result["uploads"]] == [
        ("error", "../escape.md"),
        ("upload", "wiki/index.md"),
    ]


@pytest.mark.asyncio
async def test_a_malformed_entry_is_reported_on_its_own(service) -> None:
    result = json.loads(
        await FilesToolset().upload_urls(files=["wiki/index.md", {"path": "a.md", "sha256": SHA}])
    )

    assert result["uploads"][0]["status"] == "error"
    assert result["uploads"][1]["path"] == "a.md"


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 101])
async def test_the_batch_size_is_bounded(service, count) -> None:
    result = await _upload(*[{"path": f"f{i}.md", "sha256": SHA} for i in range(count)])

    assert "error" in result
    service.authorize_put.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_file_already_stored_is_not_uploaded_again(service) -> None:
    service.head = AsyncMock(return_value={"sha256": SHA, "size": 1, "content_type": None})

    result = await _upload({"path": "wiki/index.md", "sha256": SHA})

    assert result == {"uploads": [{"path": "wiki/index.md", "status": "unchanged"}]}
    service.authorize_put.assert_not_awaited()
