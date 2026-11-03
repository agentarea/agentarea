"""A catalog provider marked first_party is the platform's own and is listed first.

The Models page badges the provider the platform hosts and puts it at the top,
reading only the spec: the catalog says which provider that is, so the webapp
never names one. The flag is a column the migrated schema must carry, written
by the sync that creates the spec and by every one after it.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID, PLATFORM_WORKSPACE_ID
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="CATALOG_TEST_DATABASE_URL not set; skipping schema-backed first-party provider tests",
)

PREFIX = "first-party-test-"
PLATFORM = UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=PLATFORM_WORKSPACE_ID)


def _key(name: str) -> str:
    return f"{PREFIX}{name}"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM provider_specs WHERE provider_key LIKE :p"), {"p": f"{PREFIX}%"}
        )
        await conn.execute(text("DELETE FROM registries WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    await engine.dispose()


@pytest.fixture
async def catalog(session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    source: dict[str, Any] = {"providers": []}
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda _url: source))
    monkeypatch.setattr(RegistryService, "_source_etag", staticmethod(lambda _url: None))
    specs = ProviderSpecRepository(session, PLATFORM)
    service = RegistryService(
        RegistryRepository(session, PLATFORM),
        RegistryItemRepository(session, PLATFORM),
        server_repo=None,  # type: ignore[arg-type]
        provider_spec_repo=specs,
    )
    with workspace_scope(PLATFORM_WORKSPACE_ID):
        registry = Registry(
            name=f"{PREFIX}providers-{uuid.uuid4().hex[:6]}",
            registry_type="llm_providers",
            source_type="url",
            source_url="providers",
        )
        session.add(registry)
        await session.commit()

    async def publish(*providers: dict[str, Any]) -> None:
        source["providers"] = [{**p, "provider_key": _key(p["provider_key"])} for p in providers]
        with workspace_scope(PLATFORM_WORKSPACE_ID):
            stats = await service.sync_registry(registry.id)
        assert stats["skipped"] == 0, stats["skipped_items"]

    async def first_party(name: str) -> bool:
        spec = await specs.get_by_provider_key(_key(name))
        assert spec is not None
        await session.refresh(spec)
        return spec.is_first_party

    async def listed() -> list[str]:
        with workspace_scope(PLATFORM_WORKSPACE_ID):
            found = await specs.list_specs(limit=1000)
        return [s.provider_key.removeprefix(PREFIX) for s in found if s.provider_key.startswith(PREFIX)]

    return publish, first_party, listed


async def test_a_first_party_entry_makes_a_first_party_spec(catalog):
    publish, first_party, _ = catalog

    await publish({"provider_key": "ours", "first_party": True}, {"provider_key": "theirs"})

    assert await first_party("ours") is True
    assert await first_party("theirs") is False


async def test_an_entry_that_drops_the_flag_clears_it(catalog):
    publish, first_party, _ = catalog
    await publish({"provider_key": "ours", "first_party": True})

    await publish({"provider_key": "ours"})

    assert await first_party("ours") is False


async def test_the_first_party_provider_is_listed_first(catalog):
    publish, _, listed = catalog

    await publish(
        {"provider_key": "anthropic", "name": "Anthropic"},
        {"provider_key": "ours", "name": "Zeta", "first_party": True},
        {"provider_key": "openai", "name": "OpenAI"},
    )

    assert await listed() == ["ours", "anthropic", "openai"]
