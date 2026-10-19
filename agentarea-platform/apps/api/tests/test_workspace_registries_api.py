"""Who may change a workspace's own registries, through the HTTP routes (ADR-0044).

A workspace admin creates, changes, syncs and removes the workspace's
registries; a member reads them and is refused the rest; another workspace's
registry is not found at all. Runs the real router and registry service over an
in-memory catalog.
"""

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_secret_catalog_service
from agentarea_api.api.v1 import registries, workspace_registries
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep, get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.di.container import register_singleton
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry, RegistryItem, RegistryItemInstall
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


ADMIN = UserContext(user_id="admin", workspace_id="acme", admin_workspaces=["acme"])
MEMBER = UserContext(user_id="member", workspace_id="acme", admin_workspaces=[])
OUTSIDER = UserContext(user_id="other-admin", workspace_id="globex", admin_workspaces=["globex"])

GITHUB = {"name": "acme-skills", "source_type": "github", "source_url": "acme/skills"}


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: BaseModel.metadata.create_all(
                c,
                tables=[
                    Registry.__table__,
                    RegistryItem.__table__,
                    RegistryItemInstall.__table__,
                ],
            )
        )
        # What a retire checks for uses of an item; other modules own these tables.
        for table in ("skills", "mcp_servers", "openapi_connections", "agents"):
            await conn.execute(text(f"CREATE TABLE {table} (registry_item_id TEXT)"))
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def secrets():
    return SimpleNamespace(
        get_for_use=AsyncMock(),
        add_reference=AsyncMock(),
        clear_references=AsyncMock(),
    )


@pytest.fixture
def caller():
    return {"context": ADMIN}


@pytest_asyncio.fixture
async def client(session, secrets, caller):
    app = FastAPI()
    for module in (registries, workspace_registries):
        app.include_router(module.router, prefix="/v1/workspaces/{workspace}")

    def service(user_context: UserContextDep) -> RegistryService:
        return RegistryService(
            RegistryRepository(session, user_context),
            RegistryItemRepository(session, user_context),
            server_repo=None,  # type: ignore[arg-type]
        )

    app.dependency_overrides[get_user_context] = lambda: caller["context"]
    app.dependency_overrides[workspace_registries.get_registry_service] = service
    app.dependency_overrides[get_secret_catalog_service] = lambda: secrets
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _path(context: UserContext, suffix: str = "") -> str:
    return f"/v1/workspaces/{context.workspace_id}/workspace-registries{suffix}"


async def _create(client, caller, context=ADMIN, **body):
    caller["context"] = context
    return await client.post(_path(context), json={**GITHUB, **body})


async def test_an_admin_creates_a_registry_for_their_workspace(client, caller):
    response = await _create(client, caller)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["scope"], body["workspace_id"], body["mode"], body["trust"]) == (
        "workspace",
        "acme",
        "mirror",
        "private",
    )


async def test_a_member_reads_but_may_not_write(client, caller):
    created = (await _create(client, caller)).json()
    caller["context"] = MEMBER

    listed = await client.get(_path(MEMBER))
    assert [r["id"] for r in listed.json()] == [created["id"]]
    assert (await client.get(_path(MEMBER, f"/{created['id']}"))).status_code == 200

    assert (await client.post(_path(MEMBER), json={**GITHUB, "name": "x"})).status_code == 403
    assert (
        await client.patch(_path(MEMBER, f"/{created['id']}"), json={"name": "renamed"})
    ).status_code == 403
    assert (await client.post(_path(MEMBER, f"/{created['id']}/sync"))).status_code == 403
    assert (await client.delete(_path(MEMBER, f"/{created['id']}"))).status_code == 403


async def test_another_workspaces_registry_is_not_found(client, caller):
    created = (await _create(client, caller)).json()
    caller["context"] = OUTSIDER

    assert (await client.get(_path(OUTSIDER, f"/{created['id']}"))).status_code == 404
    assert (
        await client.patch(_path(OUTSIDER, f"/{created['id']}"), json={"name": "mine"})
    ).status_code == 404
    assert (await client.delete(_path(OUTSIDER, f"/{created['id']}"))).status_code == 404
    assert (await client.get(_path(OUTSIDER))).json() == []
    # Nor through the platform routes, which list the platform's and the caller's own.
    platform = await client.get(f"/v1/workspaces/globex/registries/{created['id']}")
    assert platform.status_code == 404
    listed = await client.get("/v1/workspaces/globex/registries/")
    assert created["id"] not in {r["id"] for r in listed.json()}


async def test_the_platform_routes_do_not_change_a_workspace_registry(client, caller):
    created = (await _create(client, caller)).json()
    caller["context"] = UserContext(
        user_id="platform", workspace_id="platform", admin_workspaces=["platform"]
    )

    response = await client.patch(
        f"/v1/workspaces/platform/registries/{created['id']}", json={"name": "taken"}
    )
    assert response.status_code == 404


async def test_an_admin_renames_and_deletes(client, caller):
    created = (await _create(client, caller)).json()

    renamed = await client.patch(_path(ADMIN, f"/{created['id']}"), json={"name": "renamed"})
    removed = await client.delete(_path(ADMIN, f"/{created['id']}"))

    assert renamed.json()["name"] == "renamed"
    assert removed.json() == {"status": "deleted", "kept_items": 0}
    assert (await client.get(_path(ADMIN, f"/{created['id']}"))).status_code == 404


async def test_the_platforms_trust_and_types_are_refused(client, caller):
    official = await _create(client, caller, trust="official")
    mcp = await _create(client, caller, registry_type="mcp_servers")

    assert official.status_code == 422
    assert mcp.status_code == 422


async def test_credentials_are_held_by_reference(client, caller, secrets):
    secret_id = uuid4()
    secrets.get_for_use.return_value = SimpleNamespace(id=secret_id)

    body = (await _create(client, caller, credentials_secret_id=str(secret_id))).json()

    assert body["credentials_secret_id"] == str(secret_id)
    secrets.get_for_use.assert_awaited_once_with(secret_id)
    secrets.add_reference.assert_awaited_once_with(secret_id, "registry", body["id"], "credentials")


async def test_a_public_source_may_be_read_upstream(client, caller):
    response = await _create(client, caller, mode="upstream", trust="community")

    assert response.status_code == 201, response.text
    assert response.json()["mode"] == "upstream"


async def test_a_source_read_with_credentials_must_be_mirrored(client, caller, secrets):
    secret_id = uuid4()
    secrets.get_for_use.return_value = SimpleNamespace(id=secret_id)

    upstream = await _create(client, caller, mode="upstream", credentials_secret_id=str(secret_id))
    created = (await _create(client, caller, credentials_secret_id=str(secret_id))).json()
    switched = await client.patch(_path(ADMIN, f"/{created['id']}"), json={"mode": "upstream"})

    assert upstream.status_code == 400
    assert "credentials" in upstream.json()["detail"]
    assert created["mode"] == "mirror"
    assert switched.status_code == 400


@pytest.mark.parametrize(
    "source_url",
    ["/app/.env", "file:///proc/self/environ", "http://93.184.216.34/i.json", "https://10.0.0.5/i"],
)
async def test_an_index_url_is_public_https(client, caller, source_url):
    response = await _create(
        client, caller, name="idx", source_type="url", source_url=source_url, mode="upstream"
    )

    assert response.status_code == 400
    assert "public https" in response.json()["detail"]


async def test_a_failed_sync_answers_a_classification_not_the_source(client, caller, monkeypatch):
    import yaml

    async def no_etag(self, _url):
        return None

    async def leaky(self, _url):
        raise yaml.scanner.ScannerError(problem="AGENTAREA_DB_PASSWORD=hunter2: x")

    monkeypatch.setattr(RegistryService, "_untrusted_etag", no_etag)
    monkeypatch.setattr(RegistryService, "_fetch_untrusted", leaky)
    created = (
        await _create(
            client,
            caller,
            name="idx",
            source_type="url",
            source_url="https://93.184.216.34/i.json",
            mode="upstream",
        )
    ).json()

    response = await client.post(_path(ADMIN, f"/{created['id']}/sync"))
    listed = (await client.get(_path(ADMIN))).json()

    assert response.status_code == 502
    assert "hunter2" not in response.text
    assert response.json()["detail"] == "Sync failed: the source is not a valid JSON or YAML index"
    assert listed[0]["last_sync_error"] == "the source is not a valid JSON or YAML index"


async def test_sync_now_is_limited_per_workspace(client, caller, monkeypatch):
    from fastapi import HTTPException

    asked: list[tuple] = []

    async def limiter(*, scope, identity, limit):
        asked.append((scope, identity, limit))
        if len(asked) > 1:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    async def synced(self, registry_id, force=False):
        return {"new_specs": 0, "updates_flagged": 0, "unchanged": 0, "total": 0, "skipped": 0}

    monkeypatch.setattr(workspace_registries, "enforce_rate_limit", limiter)
    monkeypatch.setattr(RegistryService, "sync_registry", synced)
    created = (await _create(client, caller)).json()

    first = await client.post(_path(ADMIN, f"/{created['id']}/sync"))
    second = await client.post(_path(ADMIN, f"/{created['id']}/sync"))

    assert (first.status_code, second.status_code) == (200, 429)
    assert asked[0] == ("workspace-registry-sync", "acme", 1)
