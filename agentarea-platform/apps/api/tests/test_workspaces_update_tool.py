"""``agentarea/workspaces.update`` changes a workspace's settings; for now, its logo.

One tool, patch semantics: each setting is a parameter, so a new setting is a
new argument rather than a new tool. An MCP call cannot carry image bytes, so
the logo is read from the target workspace's own files: the caller uploads it
through the files toolset and names the path. Only an admin of that workspace
may change it, as ``PUT /v1/workspaces/{workspace}/logo`` demands, and a file
too large to be a logo is refused before its bytes are read.
"""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.api.v1 import workspaces
from agentarea_api.tools import workspaces_toolset
from agentarea_api.tools.workspaces_toolset import WorkspacesToolset
from agentarea_common.artifacts import ArtifactService
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_common.workspaces.logo import LOGO_MAX_BYTES, WorkspaceLogoStore
from botocore.exceptions import ClientError

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PNG_KEY = f"workspace-logos/ws-acme/{hashlib.sha256(PNG).hexdigest()}"


@pytest.fixture(autouse=True)
def _authz(monkeypatch):
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    monkeypatch.setattr(workspaces, "get_workspace_membership_graph", lambda: None)
    yield
    container._singletons.clear()
    container._singletons.update(saved)


def _alice(**overrides) -> UserPrincipal:
    fields = {
        "user_id": "alice",
        "accessible_workspaces": ["ws-acme", "ws-other"],
        "admin_workspaces": ["ws-acme"],
    }
    fields.update(overrides)
    return UserPrincipal(**fields)


class _Stand:
    def __init__(self, monkeypatch, *, acme_logo: str | None = None) -> None:
        self.acme = SimpleNamespace(
            id="ws-acme", slug="acme", name="Acme", owner_user_id="alice", logo_key=acme_logo
        )
        self.other = SimpleNamespace(
            id="ws-other", slug="other", name="Other", owner_user_id="bob", logo_key=None
        )
        self.session = SimpleNamespace(commit=AsyncMock())
        self.files_s3 = MagicMock()
        self.files_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        self.logos_s3 = MagicMock()
        public = MagicMock()
        public.generate_presigned_url.side_effect = lambda _op, Params, ExpiresIn: (
            f"https://s3.test/{Params['Key']}?signed"
        )
        logos = WorkspaceLogoStore(client=self.logos_s3, public_client=public, bucket="artifacts")
        files = ArtifactService(client=self.files_s3, public_client=MagicMock(), bucket="artifacts")
        by_id = {w.id: w for w in (self.acme, self.other)}
        self.repo = repo = SimpleNamespace(get=AsyncMock(side_effect=by_id.get))
        service = AsyncMock()
        service.list_for_user.return_value = [self.acme, self.other]

        @asynccontextmanager
        async def _session():
            yield self.session

        monkeypatch.setattr(
            workspaces_toolset,
            "get_database",
            lambda: SimpleNamespace(async_session_factory=_session),
        )
        monkeypatch.setattr(workspaces_toolset, "get_workspace_service", lambda *_: service)
        monkeypatch.setattr(workspaces_toolset, "ArtifactService", lambda **_kw: files)
        monkeypatch.setattr(workspaces_toolset, "WorkspaceLogoStore", lambda: logos)
        monkeypatch.setattr(workspaces_toolset, "WorkspaceRepository", lambda _s: repo)

    def store(self, workspace_id: str, path: str, data: bytes) -> None:
        key = f"workspaces/{workspace_id}/{path}"

        def head_object(Bucket, Key, **_kw):
            if Key != key:
                raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
            return {"ContentLength": len(data), "ContentType": "image/png"}

        def get_object(Bucket, Key):
            assert Key == key
            return {"Body": io.BytesIO(data), "ContentType": "image/png"}

        self.files_s3.head_object.side_effect = head_object
        self.files_s3.get_object.side_effect = get_object


async def _update(principal: UserPrincipal | None = None, **kwargs) -> dict:
    with use_mcp_user_context(principal or _alice()):
        return json.loads(await WorkspacesToolset().update(**kwargs))


@pytest.mark.asyncio
async def test_an_admin_sets_the_logo_from_a_file_in_that_workspace(monkeypatch) -> None:
    stand = _Stand(monkeypatch)
    stand.store("ws-acme", "brand/logo.png", PNG)

    result = await _update(workspace="acme", logo_path="brand/logo.png")

    assert result["logo_url"] == f"https://s3.test/{PNG_KEY}?signed"
    assert (result["slug"], result["can_administer"]) == ("acme", True)
    assert result["mcp_url"].endswith("/mcp/w/acme")
    assert stand.acme.logo_key == PNG_KEY
    put = stand.logos_s3.put_object.call_args.kwargs
    assert (put["Key"], put["ContentType"]) == (PNG_KEY, "image/png")
    stand.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_replacing_the_logo_deletes_the_previous_object(monkeypatch) -> None:
    stand = _Stand(monkeypatch, acme_logo="workspace-logos/ws-acme/old")
    stand.store("ws-acme", "brand/logo.png", PNG)

    await _update(workspace="acme", logo_path="brand/logo.png")

    stand.logos_s3.delete_object.assert_called_once_with(
        Bucket="artifacts", Key="workspace-logos/ws-acme/old"
    )


@pytest.mark.asyncio
async def test_a_member_who_does_not_administer_it_is_refused(monkeypatch) -> None:
    stand = _Stand(monkeypatch)
    stand.store("ws-other", "brand/logo.png", PNG)

    set_result = await _update(workspace="other", logo_path="brand/logo.png")
    clear_result = await _update(workspace="other", clear_logo=True)

    assert set_result == {"error": "Only a workspace admin may perform this action"}
    assert clear_result == {"error": "Only a workspace admin may perform this action"}
    stand.files_s3.head_object.assert_not_called()
    stand.logos_s3.put_object.assert_not_called()
    stand.logos_s3.delete_object.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "principal",
    [
        _alice(accessible_workspaces=["ws-other"], admin_workspaces=[]),
        _alice(bound_workspace_id="ws-other"),
    ],
    ids=["not-reached", "api-key-for-another-workspace"],
)
async def test_a_workspace_the_caller_does_not_reach_is_unknown(monkeypatch, principal) -> None:
    stand = _Stand(monkeypatch)
    stand.store("ws-acme", "brand/logo.png", PNG)

    result = await _update(principal, workspace="nope", logo_path="brand/logo.png")

    assert result == {"error": "No accessible workspace 'nope'"}
    stand.files_s3.head_object.assert_not_called()
    stand.logos_s3.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_a_file_that_is_not_a_png_jpeg_or_webp_is_refused(monkeypatch) -> None:
    stand = _Stand(monkeypatch)
    stand.store("ws-acme", "brand/logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')

    result = await _update(workspace="acme", logo_path="brand/logo.svg")

    assert result == {"error": "Logo must be a PNG, JPEG or WebP image"}
    stand.logos_s3.put_object.assert_not_called()
    assert stand.acme.logo_key is None


@pytest.mark.asyncio
async def test_an_oversize_file_is_refused_without_reading_it(monkeypatch) -> None:
    stand = _Stand(monkeypatch)
    stand.store("ws-acme", "brand/huge.png", PNG + b"\x00" * LOGO_MAX_BYTES)

    result = await _update(workspace="acme", logo_path="brand/huge.png")

    assert result == {"error": f"Logo exceeds the {LOGO_MAX_BYTES}-byte limit"}
    stand.files_s3.get_object.assert_not_called()
    stand.logos_s3.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_a_missing_file_is_reported(monkeypatch) -> None:
    stand = _Stand(monkeypatch)

    result = await _update(workspace="acme", logo_path="brand/nope.png")

    assert result == {"error": "File not found"}
    stand.logos_s3.put_object.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../ws-other/logo.png", "brand/../../x.png", "a\x00b.png"])
async def test_a_path_that_escapes_the_workspace_files_is_refused(monkeypatch, path) -> None:
    stand = _Stand(monkeypatch)

    result = await _update(workspace="acme", logo_path=path)

    assert "error" in result
    stand.files_s3.head_object.assert_not_called()
    stand.files_s3.get_object.assert_not_called()
    stand.logos_s3.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_an_admin_clears_the_logo(monkeypatch) -> None:
    stand = _Stand(monkeypatch, acme_logo=PNG_KEY)

    result = await _update(workspace="acme", clear_logo=True)

    assert result["logo_url"] is None
    assert result["slug"] == "acme"
    assert stand.acme.logo_key is None
    stand.logos_s3.delete_object.assert_called_once_with(Bucket="artifacts", Key=PNG_KEY)
    stand.session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{}, {"logo_path": "brand/logo.png", "clear_logo": True}],
    ids=["nothing", "both"],
)
async def test_an_update_must_name_exactly_one_logo_change(monkeypatch, kwargs) -> None:
    stand = _Stand(monkeypatch, acme_logo=PNG_KEY)
    stand.store("ws-acme", "brand/logo.png", PNG)

    result = await _update(workspace="acme", **kwargs)

    assert "error" in result
    stand.files_s3.head_object.assert_not_called()
    stand.logos_s3.put_object.assert_not_called()
    stand.logos_s3.delete_object.assert_not_called()
    assert stand.acme.logo_key == PNG_KEY


@pytest.mark.asyncio
async def test_a_workspace_that_vanished_mid_call_is_reported(monkeypatch) -> None:
    stand = _Stand(monkeypatch, acme_logo=PNG_KEY)
    stand.repo.get = AsyncMock(return_value=None)

    result = await _update(workspace="acme", clear_logo=True)

    assert result == {"error": "Workspace not found"}
    stand.session.commit.assert_not_awaited()
