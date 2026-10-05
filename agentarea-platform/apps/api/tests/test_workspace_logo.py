"""A workspace logo: set and cleared by its admins, shown to everyone who lists it.

The object lives outside ``workspaces/{id}/``, which is the file tree agents
read and write, so no agent can see or overwrite it. Its key is the sha256 of
its bytes, so a replaced logo has a new URL and the old object is deleted.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_api.api.v1 import workspaces
from agentarea_api.api.v1.router import principal_v1_router, workspace_v1_router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.auth.dependencies import get_principal, get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_common.workspaces.logo import LOGO_MAX_BYTES, WorkspaceLogoStore, logo_content_type
from fastapi import FastAPI
from fastapi.testclient import TestClient

WORKSPACE = "ws-acme"
LOGO_PATH = "/v1/workspaces/acme/logo"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture(autouse=True)
def _authz():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


class _Stand:
    def __init__(self, logo_key: str | None = None) -> None:
        self.workspace = SimpleNamespace(
            id=WORKSPACE, slug="acme", name="Acme", owner_user_id="user-owner", logo_key=logo_key
        )
        self.session = SimpleNamespace(commit=AsyncMock())
        self.s3 = MagicMock()
        public = MagicMock()
        public.generate_presigned_url.side_effect = lambda _op, Params, ExpiresIn: (
            f"https://s3.test/{Params['Key']}?signed"
        )
        self.logos = WorkspaceLogoStore(client=self.s3, public_client=public, bucket="artifacts")

    def client(self, context: UserContext, monkeypatch) -> TestClient:
        repo = SimpleNamespace(get=AsyncMock(return_value=self.workspace))
        monkeypatch.setattr(workspaces, "WorkspaceRepository", lambda _session: repo)
        app = FastAPI()
        app.include_router(workspace_v1_router)
        app.dependency_overrides[get_user_context] = lambda: context
        app.dependency_overrides[workspaces.get_session] = lambda: self.session
        app.dependency_overrides[workspaces.get_workspace_logo_store] = lambda: self.logos
        return TestClient(app, raise_server_exceptions=False)


def _owner() -> UserContext:
    return UserContext(
        user_id="user-owner",
        workspace_id=WORKSPACE,
        workspace_slug="acme",
        admin_workspaces=[WORKSPACE],
    )


def _member() -> UserContext:
    return UserContext(
        user_id="user-member", workspace_id=WORKSPACE, workspace_slug="acme", admin_workspaces=[]
    )


def _upload(client: TestClient, data: bytes, content_type: str = "image/png"):
    return client.put(LOGO_PATH, files={"file": ("logo.png", data, content_type)})


def test_the_owner_uploads_a_logo_and_gets_its_url(monkeypatch) -> None:
    stand = _Stand()

    response = _upload(stand.client(_owner(), monkeypatch), PNG)

    assert response.status_code == 200, response.text
    key = f"workspace-logos/{WORKSPACE}/{hashlib.sha256(PNG).hexdigest()}"
    assert response.json()["logo_url"] == f"https://s3.test/{key}?signed"
    assert response.json()["can_administer"] is True
    assert stand.workspace.logo_key == key
    put = stand.s3.put_object.call_args.kwargs
    assert (put["Bucket"], put["Key"], put["ContentType"]) == ("artifacts", key, "image/png")
    stand.session.commit.assert_awaited_once()


def test_the_logo_is_outside_the_tree_agents_read_and_write(monkeypatch) -> None:
    stand = _Stand()

    _upload(stand.client(_owner(), monkeypatch), PNG)

    assert not stand.workspace.logo_key.startswith("workspaces/")


def test_replacing_the_logo_changes_its_url_and_deletes_the_old_object(monkeypatch) -> None:
    old_key = f"workspace-logos/{WORKSPACE}/{hashlib.sha256(JPEG).hexdigest()}"
    stand = _Stand(logo_key=old_key)

    response = _upload(stand.client(_owner(), monkeypatch), WEBP, "image/webp")

    assert response.status_code == 200, response.text
    assert old_key not in response.json()["logo_url"]
    stand.s3.delete_object.assert_called_once_with(Bucket="artifacts", Key=old_key)


def test_the_type_comes_from_the_bytes_not_the_declared_content_type(monkeypatch) -> None:
    stand = _Stand()

    response = _upload(stand.client(_owner(), monkeypatch), JPEG, "image/png")

    assert response.status_code == 200, response.text
    assert stand.s3.put_object.call_args.kwargs["ContentType"] == "image/jpeg"


@pytest.mark.parametrize(
    ("data", "declared"),
    [(SVG, "image/svg+xml"), (SVG, "image/png"), (b"not an image at all", "image/png")],
)
def test_anything_but_png_jpeg_or_webp_is_rejected(monkeypatch, data, declared) -> None:
    stand = _Stand()

    response = _upload(stand.client(_owner(), monkeypatch), data, declared)

    assert response.status_code == 422, response.text
    stand.s3.put_object.assert_not_called()
    assert stand.workspace.logo_key is None


def test_a_logo_over_the_size_limit_is_rejected(monkeypatch) -> None:
    stand = _Stand()

    response = _upload(stand.client(_owner(), monkeypatch), PNG + b"\x00" * LOGO_MAX_BYTES)

    assert response.status_code == 413, response.text
    stand.s3.put_object.assert_not_called()


def test_a_member_may_neither_set_nor_clear_the_logo(monkeypatch) -> None:
    stand = _Stand(logo_key=f"workspace-logos/{WORKSPACE}/abc")
    client = stand.client(_member(), monkeypatch)

    assert _upload(client, PNG).status_code == 403
    assert client.delete(LOGO_PATH).status_code == 403
    stand.s3.put_object.assert_not_called()
    stand.s3.delete_object.assert_not_called()
    assert stand.workspace.logo_key == f"workspace-logos/{WORKSPACE}/abc"


def test_deleting_the_logo_clears_its_url_and_the_object(monkeypatch) -> None:
    key = f"workspace-logos/{WORKSPACE}/{hashlib.sha256(PNG).hexdigest()}"
    stand = _Stand(logo_key=key)

    response = stand.client(_owner(), monkeypatch).delete(LOGO_PATH)

    assert response.status_code == 200, response.text
    assert response.json()["logo_url"] is None
    assert stand.workspace.logo_key is None
    stand.s3.delete_object.assert_called_once_with(Bucket="artifacts", Key=key)
    stand.session.commit.assert_awaited_once()


def test_the_workspace_list_carries_the_logo_url(monkeypatch) -> None:
    key = f"workspace-logos/{WORKSPACE}/{hashlib.sha256(PNG).hexdigest()}"
    stand = _Stand(logo_key=key)
    plain = SimpleNamespace(
        id="user-owner", slug="owner", name="Personal", owner_user_id="user-owner", logo_key=None
    )
    service = AsyncMock()
    service.list_for_user.return_value = [plain, stand.workspace]
    monkeypatch.setattr(workspaces, "get_workspace_membership_graph", lambda: None)
    monkeypatch.setattr(workspaces, "WorkspaceLogoStore", lambda: stand.logos)
    app = FastAPI()
    app.include_router(principal_v1_router)
    app.dependency_overrides[get_principal] = lambda: UserPrincipal(
        user_id="user-owner", accessible_workspaces=[WORKSPACE], admin_workspaces=[WORKSPACE]
    )
    app.dependency_overrides[workspaces.get_workspace_service] = lambda: service

    response = TestClient(app).get("/v1/workspaces")

    assert response.status_code == 200, response.text
    assert {w["slug"]: w["logo_url"] for w in response.json()} == {
        "owner": None,
        "acme": f"https://s3.test/{key}?signed",
    }


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (WEBP, "image/webp"),
        (SVG, None),
        (b"GIF89a" + b"\x00" * 16, None),
        (b"RIFF\x24\x00\x00\x00WAVEfmt ", None),
        (b"", None),
    ],
)
def test_the_logo_type_is_read_from_magic_bytes(data: bytes, expected: str | None) -> None:
    assert logo_content_type(data) == expected
