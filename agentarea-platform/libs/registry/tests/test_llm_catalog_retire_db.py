"""A provider or model the LLM catalog drops leaves provider_specs, unless a workspace uses it.

Every synced provider and model has an entity (its provider_specs or model_specs
row), and the generic cleanup keeps any item with one, so a dropped provider
stayed on the Models page forever. "Uses it" is a provider config, a model
instance, or a workspace's own copy of a model, in any workspace, and deleting
a provider cascades through foreign keys only the migrated schema has.
"""

import hashlib
import json
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.constants import (
    MANAGED_BY_PLATFORM,
    PLATFORM_PRINCIPAL_ID,
    PLATFORM_WORKSPACE_ID,
)
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="CATALOG_TEST_DATABASE_URL not set; skipping schema-backed LLM catalog retire tests",
)

PREFIX = "llm-retire-test-"
WORKSPACE_A = "llm-retire-test-ws-a"
WORKSPACE_B = "llm-retire-test-ws-b"
PLATFORM = UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=PLATFORM_WORKSPACE_ID)


def _key(name: str) -> str:
    return f"{PREFIX}{name}"


def _providers(*names: str) -> dict[str, Any]:
    return {"providers": [{"provider_key": _key(n), "name": n} for n in names]}


def _models(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {
        "models": [
            {
                "provider_key": _key(provider),
                "model_name": model,
                "context_window": 8192,
                "input_cost_per_token": "0.000001",
                "output_cost_per_token": "0.000002",
            }
            for provider, model in pairs
        ]
    }


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield eng
    async with eng.begin() as conn:
        await conn.execute(
            text("DELETE FROM provider_specs WHERE provider_key LIKE :p"), {"p": f"{PREFIX}%"}
        )
        await conn.execute(text("DELETE FROM registries WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest.fixture
async def enforced(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    # Production reconciles and serves the API under AGENTAREA_DB_TENANT_SCOPE=enforce.
    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
    )
    async with maker() as s:
        yield s


class Catalog:
    """The two LLM catalog files, synced the way the platform reconcile syncs them."""

    def __init__(self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch, etags: bool = False):
        self.session = session
        self.payloads: dict[str, dict[str, Any]] = {}
        monkeypatch.setattr(
            RegistryService, "_fetch_source", staticmethod(lambda url: self.payloads[url])
        )
        # With etags, a source answers HEAD with a digest of what it serves, as
        # S3 does, so a sync of an unchanged file skips it.
        monkeypatch.setattr(
            RegistryService,
            "_source_etag",
            staticmethod(lambda url: self._etag(url) if etags else None),
        )
        self.service = RegistryService(
            RegistryRepository(session, PLATFORM),
            RegistryItemRepository(session, PLATFORM),
            server_repo=None,  # type: ignore[arg-type]
            provider_spec_repo=ProviderSpecRepository(session, PLATFORM),
            model_spec_repo=ModelSpecRepository(session, PLATFORM),
        )
        self.registries: dict[str, uuid.UUID] = {}

    def _etag(self, url: str) -> str:
        body = json.dumps(self.payloads[url], sort_keys=True).encode()
        return hashlib.sha256(body).hexdigest()

    async def publish(self, providers: dict[str, Any], models: dict[str, Any]) -> None:
        self.payloads = {"providers": providers, "models": models}
        with workspace_scope(PLATFORM_WORKSPACE_ID):
            if not self.registries:
                for name, registry_type in (
                    ("providers", "llm_providers"),
                    ("models", "llm_models"),
                ):
                    reg = Registry(
                        name=f"{PREFIX}{name}-{uuid.uuid4().hex[:6]}",
                        registry_type=registry_type,
                        source_type="url",
                        source_url=name,
                    )
                    self.session.add(reg)
                    await self.session.commit()
                    self.registries[name] = reg.id
            for name in ("providers", "models"):
                stats = await self.service.sync_registry(self.registries[name])
                assert stats["skipped"] == 0, stats["skipped_items"]


async def _provider_keys(session: AsyncSession) -> set[str]:
    rows = await session.execute(
        text("SELECT provider_key FROM provider_specs WHERE provider_key LIKE :p"),
        {"p": f"{PREFIX}%"},
    )
    return set(rows.scalars().all())


async def _model_names(session: AsyncSession) -> set[str]:
    rows = await session.execute(
        text(
            "SELECT ms.model_name FROM model_specs ms "
            "JOIN provider_specs ps ON ps.id = ms.provider_spec_id WHERE ps.provider_key LIKE :p"
        ),
        {"p": f"{PREFIX}%"},
    )
    return set(rows.scalars().all())


async def _items(session: AsyncSession) -> dict[str, bool]:
    rows = await session.execute(
        text(
            "SELECT ri.external_id, ri.in_source FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id WHERE r.name LIKE :p"
        ),
        {"p": f"{PREFIX}%"},
    )
    return dict(rows.tuples().all())


async def _spec_id(session: AsyncSession, provider: str) -> uuid.UUID:
    return (
        await session.execute(
            text("SELECT id FROM provider_specs WHERE provider_key = :k"), {"k": _key(provider)}
        )
    ).scalar_one()


async def _model_spec_id(session: AsyncSession, provider: str, model: str) -> uuid.UUID:
    return (
        await session.execute(
            text(
                "SELECT ms.id FROM model_specs ms JOIN provider_specs ps "
                "ON ps.id = ms.provider_spec_id "
                "WHERE ps.provider_key = :k AND ms.model_name = :m AND ms.workspace_id = :w"
            ),
            {"k": _key(provider), "m": model, "w": PLATFORM_WORKSPACE_ID},
        )
    ).scalar_one()


async def _config(
    session: AsyncSession, provider: str, workspace: str, managed_by: str | None = None
) -> uuid.UUID:
    config = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO provider_configs (id, provider_spec_id, name, is_active, is_public, "
            "managed_by, workspace_id, created_by) "
            "VALUES (:id, :spec, 'mine', true, false, :managed, :w, 'u')"
        ),
        {
            "id": config,
            "spec": await _spec_id(session, provider),
            "managed": managed_by,
            "w": workspace,
        },
    )
    await session.commit()
    return config


async def _instance(
    session: AsyncSession, config: uuid.UUID, model_spec: uuid.UUID, workspace: str
) -> None:
    await session.execute(
        text(
            "INSERT INTO model_instances (id, provider_config_id, model_spec_id, name, "
            "is_active, is_public, tags, workspace_id, created_by) "
            "VALUES (:id, :config, :spec, 'mine', true, false, '[]', :w, 'u')"
        ),
        {"id": uuid.uuid4(), "config": config, "spec": model_spec, "w": workspace},
    )
    await session.commit()


async def _listed(session: AsyncSession, workspace: str) -> set[str]:
    ctx = UserContext(user_id="u", workspace_id=workspace)
    with workspace_scope(workspace):
        specs = await ProviderSpecRepository(session, ctx).list_specs(limit=1000)
    return {s.provider_key for s in specs if s.provider_key.startswith(PREFIX)}


async def test_a_dropped_provider_nothing_uses_goes_with_its_models_and_items(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(
        _providers("kept", "dropped"), _models(("kept", "k-1"), ("dropped", "d-1"))
    )
    assert await _provider_keys(session) == {_key("kept"), _key("dropped")}

    await catalog.publish(_providers("kept"), _models(("kept", "k-1")))

    assert await _provider_keys(session) == {_key("kept")}
    assert await _model_names(session) == {"k-1"}
    assert await _items(session) == {_key("kept"): True, f"{_key('kept')}/k-1": True}


@pytest.mark.parametrize("first", ["providers", "models"])
async def test_a_dropped_provider_goes_whichever_catalog_file_syncs_first(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch, first: str
):
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(
        _providers("other", "dropped"), _models(("other", "o-1"), ("dropped", "d-1"))
    )
    catalog.payloads = {"providers": _providers("other"), "models": _models(("other", "o-1"))}
    with workspace_scope(PLATFORM_WORKSPACE_ID):
        await catalog.service.sync_registry(catalog.registries[first])

    assert await _provider_keys(session) == (
        {_key("other")} if first == "providers" else {_key("other"), _key("dropped")}
    )
    assert await _model_names(session) == {"o-1"}
    left = await _items(session)
    assert f"{_key('dropped')}/d-1" not in left

    with workspace_scope(PLATFORM_WORKSPACE_ID):
        await catalog.service.sync_registry(
            catalog.registries["models" if first == "providers" else "providers"]
        )

    assert await _provider_keys(session) == {_key("other")}
    assert await _items(session) == {_key("other"): True, f"{_key('other')}/o-1": True}


async def test_a_dropped_provider_a_workspace_configured_stays_for_that_workspace_only(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(
        _providers("kept", "dropped"), _models(("kept", "k-1"), ("dropped", "d-1"))
    )
    config = await _config(session, "dropped", WORKSPACE_A)
    await _instance(session, config, await _model_spec_id(session, "dropped", "d-1"), WORKSPACE_A)

    await catalog.publish(_providers("kept"), _models(("kept", "k-1")))

    assert await _provider_keys(session) == {_key("kept"), _key("dropped")}
    assert await _model_names(session) == {"k-1", "d-1"}
    assert await _items(session) == {
        _key("kept"): True,
        f"{_key('kept')}/k-1": True,
        _key("dropped"): False,
        f"{_key('dropped')}/d-1": False,
    }
    assert await _listed(enforced, WORKSPACE_A) == {_key("kept"), _key("dropped")}
    assert await _listed(enforced, WORKSPACE_B) == {_key("kept")}


async def test_a_platform_config_on_a_dropped_provider_keeps_it_offered_to_every_workspace(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    # Every workspace reads a platform-managed config and runs its models.
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(_providers("dropped"), _models(("dropped", "d-1")))
    await _config(session, "dropped", PLATFORM_WORKSPACE_ID, managed_by=MANAGED_BY_PLATFORM)

    await catalog.publish(_providers("other"), _models())

    assert await _provider_keys(session) == {_key("other"), _key("dropped")}
    assert await _listed(enforced, WORKSPACE_B) == {_key("other"), _key("dropped")}


async def test_a_model_instance_through_another_providers_config_keeps_the_provider(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    # An instance's config and model spec need not share a provider.
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(
        _providers("kept", "dropped"), _models(("kept", "k-1"), ("dropped", "d-1"))
    )
    config = await _config(session, "kept", WORKSPACE_A)
    await _instance(session, config, await _model_spec_id(session, "dropped", "d-1"), WORKSPACE_A)

    await catalog.publish(_providers("kept"), _models(("kept", "k-1")))

    assert await _provider_keys(session) == {_key("kept"), _key("dropped")}
    assert await _model_names(session) == {"k-1", "d-1"}
    assert await _listed(enforced, WORKSPACE_A) == {_key("kept"), _key("dropped")}
    assert await _listed(enforced, WORKSPACE_B) == {_key("kept")}


async def test_a_workspaces_own_copy_of_a_model_keeps_the_provider(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(_providers("dropped"), _models(("dropped", "d-1")))
    await session.execute(
        text(
            "INSERT INTO model_specs (id, provider_spec_id, model_name, display_name, kind, "
            "is_active, workspace_id, created_by) VALUES (:id, :p, 'd-1', 'd-1', 'chat', true, "
            ":w, 'u')"
        ),
        {"id": uuid.uuid4(), "p": await _spec_id(session, "dropped"), "w": WORKSPACE_A},
    )
    await session.commit()

    await catalog.publish(_providers("other"), _models())

    assert _key("dropped") in await _provider_keys(session)
    assert await _listed(enforced, WORKSPACE_A) == {_key("other"), _key("dropped")}
    assert await _listed(enforced, WORKSPACE_B) == {_key("other")}


async def test_a_provider_dropped_then_published_again_gets_its_unchanged_models_back(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    # The provider's cleanup deletes the models file's items, so that file's
    # stored ETag no longer describes what was applied from it; an unchanged
    # file skipped on its ETag would leave the provider with no models.
    catalog = Catalog(enforced, monkeypatch, etags=True)
    models = _models(("kept", "k-1"), ("back", "b-1"))
    await catalog.publish(_providers("kept", "back"), models)

    catalog.payloads["providers"] = _providers("kept")
    with workspace_scope(PLATFORM_WORKSPACE_ID):
        await catalog.service.sync_registry(catalog.registries["providers"])
    assert await _provider_keys(session) == {_key("kept")}
    assert await _model_names(session) == {"k-1"}

    await catalog.publish(_providers("kept", "back"), models)

    assert await _provider_keys(session) == {_key("kept"), _key("back")}
    assert await _model_names(session) == {"k-1", "b-1"}
    assert await _items(session) == {
        _key("kept"): True,
        _key("back"): True,
        f"{_key('kept')}/k-1": True,
        f"{_key('back')}/b-1": True,
    }


async def test_a_dropped_model_of_a_kept_provider_goes_unless_an_instance_uses_it(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(
        _providers("kept"), _models(("kept", "stays"), ("kept", "unused"), ("kept", "used"))
    )
    config = await _config(session, "kept", WORKSPACE_A)
    await _instance(session, config, await _model_spec_id(session, "kept", "used"), WORKSPACE_A)

    await catalog.publish(_providers("kept"), _models(("kept", "stays")))

    assert await _model_names(session) == {"stays", "used"}
    assert await _items(session) == {
        _key("kept"): True,
        f"{_key('kept')}/stays": True,
        f"{_key('kept')}/used": False,
    }


async def test_a_provider_another_catalog_still_publishes_stays(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    # Two platform registries publishing one provider_key share its one spec.
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(_providers("shared"), _models(("shared", "s-1")))
    with workspace_scope(PLATFORM_WORKSPACE_ID):
        regional = Registry(
            name=f"{PREFIX}regional",
            registry_type="llm_providers",
            source_type="url",
            source_url="regional",
        )
        enforced.add(regional)
        await enforced.commit()
        catalog.payloads["regional"] = _providers("shared")
        await catalog.service.sync_registry(regional.id)
        catalog.payloads["providers"] = _providers("other")
        await catalog.service.sync_registry(catalog.registries["providers"])

    assert await _provider_keys(session) == {_key("shared"), _key("other")}
    assert await _model_names(session) == {"s-1"}
    assert await _listed(enforced, WORKSPACE_B) == {_key("shared"), _key("other")}


async def test_an_empty_catalog_retires_nothing(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(_providers("kept"), _models(("kept", "k-1")))

    await catalog.publish({"providers": []}, {"models": []})

    assert await _provider_keys(session) == {_key("kept")}
    assert await _model_names(session) == {"k-1"}
    assert await _items(session) == {_key("kept"): True, f"{_key('kept')}/k-1": True}
    assert await _listed(enforced, WORKSPACE_B) == {_key("kept")}


async def test_retiring_a_provider_registry_deletes_the_providers_nothing_uses(
    session: AsyncSession, enforced: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    catalog = Catalog(enforced, monkeypatch)
    await catalog.publish(_providers("unused", "used"), _models(("unused", "u-1")))
    await _config(session, "used", WORKSPACE_A)

    with workspace_scope(PLATFORM_WORKSPACE_ID):
        await catalog.service.retire_registry(catalog.registries["providers"])

    assert await _provider_keys(session) == {_key("used")}
    assert await _model_names(session) == set()
    assert await _items(session) == {_key("used"): False}
