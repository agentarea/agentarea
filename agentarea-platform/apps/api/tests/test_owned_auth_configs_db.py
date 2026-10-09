"""An auth config minted by a connect flow goes with the connection it was minted for.

Catalog OAuth and MCP OAuth connects create one auth config per connection or
instance, attached only once the provider calls back. Deleting the owner left the
config, its credential and its secret references behind -- attached or not. The
rows go together by ON DELETE CASCADE, which only the migrated schema holds; the
credential and the references, kept elsewhere, are discarded first.

Needs a PostgreSQL migrated to head; skips without one:

    OPENAPI_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/agentarea_test  # pragma: allowlist secret
"""

import importlib.util
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import agentarea_registry.domain.models  # noqa: F401  (openapi_connections.registry_item_id)
import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.testing.mocks import TestSecretManager
from agentarea_common.utils.url_safety import OutboundPolicy
from agentarea_mcp.application.auth_resolver import build_owned_auth_releaser
from agentarea_mcp.application.auth_service import MCPAuthService
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
from agentarea_openapi.application.service import OpenAPIConnectionService
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_secrets.catalog_service import SecretCatalogService
from agentarea_secrets.models import EncryptedSecret
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("OPENAPI_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="OPENAPI_TEST_DATABASE_URL not set; skipping schema-backed auth config tests",
)

WORKSPACE = "owned-auth-config-ws"
USER = "user-1"
CONTEXT = UserContext(user_id=USER, workspace_id=WORKSPACE)
OAUTH = {
    "provider": "yandex",
    "token_url": "https://oauth.example.com/token",
    "client_id": "cid",
    "credential_mode": "custom",
}
MIGRATION = Path(__file__).resolve().parents[1] / (
    "alembic/versions/20261009_1700_auth_config_owner.py"
)


@pytest.fixture(autouse=True)
def _no_graph():
    with patch(
        "agentarea_common.base.workspace_scoped_repository.revoke_resource", AsyncMock()
    ):
        yield


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        await _cleanup(s)
        yield s
        await _cleanup(s)
    await engine.dispose()


async def _cleanup(s: AsyncSession) -> None:
    for table in (
        "secret_references",
        "openapi_connections",
        "mcp_server_instances",
        "mcp_auth_configs",
        "encrypted_secrets",
    ):
        await s.execute(text(f"DELETE FROM {table} WHERE workspace_id = :ws"), {"ws": WORKSPACE})  # noqa: S608
    await s.commit()


async def _connection(s: AsyncSession, **fields) -> uuid.UUID:
    connection_id = uuid.uuid4()
    with workspace_scope(WORKSPACE):
        s.add(
            OpenAPIConnection(
                id=connection_id,
                name="Metrica",
                base_url="https://api-metrika.yandex.net",
                workspace_id=WORKSPACE,
                created_by=USER,
                **fields,
            )
        )
        await s.commit()
    return connection_id


async def _instance(s: AsyncSession, **fields) -> uuid.UUID:
    instance = MCPServerInstance(
        name="remote",
        server_spec_id=str(uuid.uuid4()),
        transport="url",
        json_spec={"endpoint_url": "https://mcp.example.com/mcp", "env_vars": ["X-Api-Key"]},
        workspace_id=WORKSPACE,
        created_by=USER,
        **fields,
    )
    with workspace_scope(WORKSPACE):
        s.add(instance)
        await s.commit()
    return instance.id


async def _auth_config(s: AsyncSession, secrets: TestSecretManager, name: str, **owner):
    service = MCPAuthService(MCPAuthConfigRepository(s, CONTEXT), secrets)
    with workspace_scope(WORKSPACE):
        return await service.create(
            name=name,
            auth_type="oauth2",
            config=OAUTH,
            credentials={"client_secret": "shh", "access_token": "tok"},
            allow_managed_credentials=True,
            **owner,
        )


async def _referenced_secret(s: AsyncSession, secrets: TestSecretManager, config_id) -> None:
    secret = EncryptedSecret(
        workspace_id=WORKSPACE,
        secret_name="yandex-client-secret",
        encrypted_value="ciphertext",
        created_by=USER,
    )
    s.add(secret)
    await s.commit()
    catalog = SecretCatalogService(session=s, user_context=CONTEXT, secret_manager=secrets)
    await catalog.add_reference(secret.id, "mcp_auth_config", str(config_id), "client_secret")


async def _exists(s: AsyncSession, table: str, row_id) -> bool:
    result = await s.execute(
        text(f"SELECT 1 FROM {table} WHERE id = :id"),  # noqa: S608
        {"id": row_id},
    )
    return result.first() is not None


async def _references(s: AsyncSession, config_id) -> int:
    result = await s.execute(
        text("SELECT count(*) FROM secret_references WHERE consumer_id = :id"),
        {"id": str(config_id)},
    )
    return int(result.scalar_one())


def _connection_service(s: AsyncSession, secrets: TestSecretManager) -> OpenAPIConnectionService:
    factory = RepositoryFactory(s, CONTEXT)
    return OpenAPIConnectionService(
        repository_factory=factory,
        secret_manager=secrets,
        auth_config_access_checker=AsyncMock(),
        owned_auth_releaser=build_owned_auth_releaser(factory, secrets),
        outbound_policy=OutboundPolicy(),
    )


@pytest.mark.asyncio
async def test_deleting_a_connection_deletes_the_auth_config_minted_for_it(session) -> None:
    secrets = TestSecretManager()
    conn_id = await _connection(session)
    config = await _auth_config(session, secrets, "yandex-conn", openapi_connection_id=conn_id)
    await _referenced_secret(session, secrets, config.id)
    with workspace_scope(WORKSPACE):
        await session.execute(
            text("UPDATE openapi_connections SET auth_config_id = :c WHERE id = :id"),
            {"c": config.id, "id": conn_id},
        )
        await session.commit()

        assert await _connection_service(session, secrets).delete_connection(conn_id)

    assert not await _exists(session, "openapi_connections", conn_id)
    assert not await _exists(session, "mcp_auth_configs", config.id)
    assert secrets.get_all_secrets() == {}
    assert await _references(session, config.id) == 0


@pytest.mark.asyncio
async def test_a_connect_flow_never_finished_is_deleted_with_its_connection(session) -> None:
    # The provider never called back, so the connection never pointed at it.
    secrets = TestSecretManager()
    conn_id = await _connection(session, status="pending")
    config = await _auth_config(session, secrets, "yandex-pending", openapi_connection_id=conn_id)

    with workspace_scope(WORKSPACE):
        assert await _connection_service(session, secrets).delete_connection(conn_id)

    assert not await _exists(session, "mcp_auth_configs", config.id)
    assert secrets.get_all_secrets() == {}


@pytest.mark.asyncio
async def test_a_shared_auth_config_the_connection_only_uses_survives(session) -> None:
    secrets = TestSecretManager()
    shared = await _auth_config(session, secrets, "admin-shared")
    conn_id = await _connection(session, auth_config_id=shared.id)

    with workspace_scope(WORKSPACE):
        assert await _connection_service(session, secrets).delete_connection(conn_id)

    assert await _exists(session, "mcp_auth_configs", shared.id)
    assert shared.secret_key in secrets.get_all_secrets()


@pytest.mark.asyncio
async def test_deleting_an_instance_deletes_its_auth_configs_and_env_secrets(session) -> None:
    from agentarea_mcp.application.service import MCPServerInstanceService

    secrets = TestSecretManager()
    instance_id = await _instance(session)
    attached = await _auth_config(session, secrets, "mcp-attached", mcp_instance_id=instance_id)
    abandoned = await _auth_config(session, secrets, "mcp-abandoned", mcp_instance_id=instance_id)
    shared = await _auth_config(session, secrets, "admin-shared")
    await secrets.set_secret(f"mcp_instance_{instance_id}_X-Api-Key", "canary")
    with workspace_scope(WORKSPACE):
        await session.execute(
            text("UPDATE mcp_server_instances SET auth_config_id = :c WHERE id = :id"),
            {"c": attached.id, "id": instance_id},
        )
        await session.commit()

        with patch("agentarea_mcp.application.service.get_database", MagicMock()):
            service = MCPServerInstanceService(
                repository_factory=RepositoryFactory(session, CONTEXT),
                event_broker=AsyncMock(),
                secret_manager=secrets,
                era_verdict_store=MagicMock(),
            )
        assert await service.delete_instance(instance_id)

    assert not await _exists(session, "mcp_server_instances", instance_id)
    assert not await _exists(session, "mcp_auth_configs", attached.id)
    assert not await _exists(session, "mcp_auth_configs", abandoned.id)
    assert await _exists(session, "mcp_auth_configs", shared.id)
    assert set(secrets.get_all_secrets()) == {shared.secret_key}


@pytest.mark.asyncio
async def test_an_auth_config_has_at_most_one_owner(session) -> None:
    secrets = TestSecretManager()
    conn_id = await _connection(session)
    instance_id = await _instance(session)

    with pytest.raises(Exception, match="ck_mcp_auth_configs_one_owner"):
        await _auth_config(
            session,
            secrets,
            "both",
            openapi_connection_id=conn_id,
            mcp_instance_id=instance_id,
        )


def _backfill() -> list[str]:
    spec = importlib.util.spec_from_file_location("auth_config_owner", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BACKFILL


async def _bare_config(s: AsyncSession, name: str, config: str) -> uuid.UUID:
    config_id = uuid.uuid4()
    await s.execute(
        text(
            "INSERT INTO mcp_auth_configs (id, workspace_id, created_by, name, auth_type, config, "
            "created_at, updated_at) VALUES (:id, :ws, :user, :name, 'oauth2', "
            "CAST(:config AS json), now(), now())"
        ),
        {"id": config_id, "ws": WORKSPACE, "user": USER, "name": name, "config": config},
    )
    await s.commit()
    return config_id


async def _owner(s: AsyncSession, config_id) -> tuple:
    result = await s.execute(
        text("SELECT openapi_connection_id, mcp_instance_id FROM mcp_auth_configs WHERE id = :id"),
        {"id": config_id},
    )
    return tuple(result.one())


@pytest.mark.asyncio
async def test_the_backfill_gives_each_minted_config_its_owner(session) -> None:
    instance_id = await _instance(session)
    conn_id = await _connection(session)
    minted_mcp = await _bare_config(
        session, f"mcp-oauth-{str(instance_id)[:8]}", '{"credential_mode": "auto"}'
    )
    minted_catalog = await _bare_config(
        session,
        f"yandex-{str(conn_id)[:8]}",
        '{"provider": "yandex", "credential_mode": "custom"}',
    )
    admin_made = await _bare_config(
        session, f"mcp-oauth-{str(instance_id)[:8]}", '{"token_url": "https://t"}'
    )
    owner_gone = await _bare_config(session, "mcp-oauth-00000000", '{"credential_mode": "auto"}')

    for statement in _backfill():
        await session.execute(text(statement))
    await session.commit()

    assert await _owner(session, minted_mcp) == (None, instance_id)
    assert await _owner(session, minted_catalog) == (conn_id, None)
    assert await _owner(session, admin_made) == (None, None)
    assert await _owner(session, owner_gone) == (None, None)
