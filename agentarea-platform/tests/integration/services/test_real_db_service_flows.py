from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.domain.models import ProviderSpec
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from agentarea_mcp.application.compound_service import CompoundMCPService
from agentarea_mcp.application.registry_service import RegistryService
from agentarea_mcp.infrastructure.auth_repository import CompoundMCPRepository
from agentarea_mcp.infrastructure.registry_repository import RegistryItemRepository, RegistryRepository
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository, MCPServerRepository
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


class InMemorySecretManager(BaseSecretManager):
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    async def get_secret(self, secret_name: str) -> str | None:
        return self._secrets.get(secret_name)

    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        self._secrets[secret_name] = secret_value

    async def delete_secret(self, secret_name: str) -> None:
        self._secrets.pop(secret_name, None)


@pytest_asyncio.fixture
async def db_session():
    url = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'aiagents')}"
    )
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest.fixture
def user_context() -> UserContext:
    suffix = uuid4().hex[:8]
    return UserContext(user_id=f"svc-user-{suffix}", workspace_id=f"svc-ws-{suffix}", roles=["user"])


@pytest.mark.asyncio
async def test_provider_service_create_and_delete_config_with_real_db(db_session, user_context):
    service = ProviderService(
        provider_spec_repo=ProviderSpecRepository(db_session, user_context),
        provider_config_repo=ProviderConfigRepository(db_session, user_context),
        model_spec_repo=ModelSpecRepository(db_session, user_context),
        model_instance_repo=ModelInstanceRepository(db_session, user_context),
        event_broker=None,
        secret_manager=InMemorySecretManager(),
    )

    provider_spec = ProviderSpec(
        provider_key=f"it-provider-{uuid4().hex[:12]}",
        name="Integration Provider",
        provider_type="openai",
        workspace_id=user_context.workspace_id,
        created_by=user_context.user_id,
    )
    await service.provider_spec_repo.create(provider_spec)
    await db_session.commit()

    config = await service.create_provider_config(
        provider_spec_id=provider_spec.id,
        name="Integration Config",
        api_key="super-secret-key",
        endpoint_url="https://example.local",
        created_by=user_context.user_id,
    )

    secret_name = f"provider_config_{config.id}"
    assert config.api_key == secret_name
    assert await service.secret_manager.get_secret(secret_name) == "super-secret-key"
    assert (await service.get_provider_config(config.id)) is not None

    assert await service.delete_provider_config(config.id) is True
    assert await service.get_provider_config(config.id) is None
    assert await service.secret_manager.get_secret(secret_name) is None


@pytest.mark.asyncio
async def test_compound_mcp_service_member_lifecycle_with_real_db(db_session, user_context):
    service = CompoundMCPService(CompoundMCPRepository(db_session, user_context))
    mcp_instance_repo = MCPServerInstanceRepository(db_session, user_context)

    compound = await service.create(name=f"compound-{uuid4().hex[:6]}")

    mcp_instance_1 = await mcp_instance_repo.create(
        name=f"instance-1-{uuid4().hex[:4]}",
        description="first",
        server_spec_id="test/server:1",
        json_spec={"env_vars": []},
        status="active",
    )
    mcp_instance_2 = await mcp_instance_repo.create(
        name=f"instance-2-{uuid4().hex[:4]}",
        description="second",
        server_spec_id="test/server:2",
        json_spec={"env_vars": []},
        status="active",
    )

    await service.add_member(compound.id, mcp_instance_1.id, order=20, config={"namespace_prefix": "ns2"})
    await service.add_member(compound.id, mcp_instance_2.id, order=10, config={"namespace_prefix": "ns1"})

    members = await service.get_members(compound.id)
    assert [member.order for member in members] == [10, 20]

    assert await service.remove_member(compound.id, mcp_instance_1.id) is True
    remaining = await service.get_members(compound.id)
    assert len(remaining) == 1
    assert remaining[0].mcp_instance_id == mcp_instance_2.id


@pytest.mark.asyncio
async def test_registry_service_create_and_list_items_with_real_db(db_session, user_context):
    service = RegistryService(
        RegistryRepository(db_session, user_context),
        RegistryItemRepository(db_session, user_context),
        MCPServerRepository(db_session, user_context),
    )

    registry = await service.create_registry(
        name="Integration Registry",
        registry_type="mcp_servers",
        source_type="url",
        source_url="https://registry.example.local/servers.json",
    )

    await service.item_repo.create(
        registry_id=registry.id,
        external_id=f"tool-{uuid4().hex[:6]}",
        name="Search Tool",
        description="search provider",
        version="1.0.0",
        tags=["search", "data"],
        spec={"connection_type": "url", "url": "https://tool.example"},
    )
    await service.item_repo.create(
        registry_id=registry.id,
        external_id=f"tool-{uuid4().hex[:6]}",
        name="Vector Tool",
        description="vector provider",
        version="1.1.0",
        tags=["vector", "data"],
        spec={"connection_type": "url", "url": "https://vector.example"},
    )

    items = await service.list_items(registry.id)
    assert len(items) == 2


@pytest.mark.asyncio
async def test_registry_service_search_catalog_filters_with_real_db(db_session, user_context):
    service = RegistryService(
        RegistryRepository(db_session, user_context),
        RegistryItemRepository(db_session, user_context),
        MCPServerRepository(db_session, user_context),
    )

    registry = await service.create_registry(
        name="Search Registry",
        registry_type="mcp_servers",
        source_type="url",
        source_url="https://registry.example.local/search.json",
    )

    await service.item_repo.create(
        registry_id=registry.id,
        external_id=f"item-{uuid4().hex[:6]}",
        name="OpenAI Connector",
        description="llm endpoint",
        version="1.0.0",
        tags=["llm", "official"],
        spec={"connection_type": "url", "url": "https://openai.example"},
    )
    await service.item_repo.create(
        registry_id=registry.id,
        external_id=f"item-{uuid4().hex[:6]}",
        name="Local Embedder",
        description="local embedding provider",
        version="1.0.0",
        tags=["llm", "local"],
        spec={"connection_type": "url", "url": "https://local.example"},
    )

    query_results = await service.search_catalog(query="OpenAI")
    tag_results = await service.search_catalog(tag="local")
    assert len(query_results) == 1
    assert query_results[0].name == "OpenAI Connector"
    assert len(tag_results) == 1
    assert tag_results[0].name == "Local Embedder"
