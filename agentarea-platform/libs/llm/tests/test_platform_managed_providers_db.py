"""Platform-managed providers, against a real schema.

The rule under test is a visibility rule expressed in SQL — a platform-managed
configuration is readable from every workspace, writable from none — and a mocked
session has no idea what a WHERE clause does. These drive the real repositories
against a migrated database for the same reason the secret-lifecycle tests next
door do: the mocked version of this would pass no matter which way the filter went.

The rows are written here the way ``agentarea-operator`` writes them, not through a
helper that ships with the application: nothing inside this process is allowed to
create them. That is the point of the write guard, and a fixture that went around
it would be testing a path no caller has.

Needs a PostgreSQL migrated to head; skips without one:

    LLM_TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:55471/agentarea_test  # pragma: allowlist secret
"""

import os
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from agentarea_common.auth import UserContext
from agentarea_common.constants import MANAGED_BY_PLATFORM, PLATFORM_WORKSPACE_ID
from agentarea_common.platform_ids import platform_config_id, platform_instance_id
from agentarea_llm.application.provider_service import (
    PlatformManagedConfigError,
    _reject_platform_managed,
)
from agentarea_llm.domain.models import (
    ModelInstance,
    ModelSpec,
    ProviderConfig,
    ProviderSpec,
)
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("LLM_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="LLM_TEST_DATABASE_URL not set; skipping schema-backed platform provider tests",
)

# Secret NAMES, not secrets — the whole point of managed_by is that these say where
# a key lives rather than being one. What differs between the two is the workspace
# whose secret store the name is resolved against. Named rather than inlined so the
# allowlist pragma sits on a line by itself: ruff reflowed an earlier inline assert
# across two lines and left the pragma on the closing paren, where detect-secrets
# stopped seeing it.
PLATFORM_SECRET_NAME = "platformtest"  # pragma: allowlist secret
TENANT_SECRET_NAME = "tenant-key"  # pragma: allowlist secret

TENANT_A = "platform-test-tenant-a"
TENANT_B = "platform-test-tenant-b"
PROVIDER_KEY = "platform-test-openai"
MODEL_NAME = "test-model-mini"
PLATFORM_CONFIG_NAME = "AgentArea (included)"
ENDPOINT_URL = "https://llm.example.invalid/v1"


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
    for table in ("model_instances", "model_specs", "provider_configs", "provider_specs"):
        await s.execute(
            text(f"DELETE FROM {table} WHERE workspace_id = ANY(:ws)"),
            {"ws": [TENANT_A, TENANT_B, PLATFORM_WORKSPACE_ID]},
        )
    await s.commit()


async def _provider_spec(s: AsyncSession) -> ProviderSpec:
    spec = ProviderSpec(
        id=uuid.uuid4(),
        provider_key=PROVIDER_KEY,
        name="Platform Test Provider",
        provider_type="openai",
        is_builtin=True,
        workspace_id=PLATFORM_WORKSPACE_ID,
        created_by="test",
    )
    s.add(spec)
    await s.commit()
    return spec


async def _install_platform_model(s: AsyncSession, spec: ProviderSpec) -> None:
    """Write the four rows the operator writes, with the ids it derives.

    Kept faithful to the operator rather than convenient: the ids come from the
    shared recipe because billing's rate cards name them, ``managed_by`` is set on
    the configuration rather than inferred from the workspace, and ``api_key`` holds
    a secret name rather than a key.
    """
    config = ProviderConfig(
        id=platform_config_id(PROVIDER_KEY),
        provider_spec_id=spec.id,
        name=PLATFORM_CONFIG_NAME,
        api_key=PLATFORM_SECRET_NAME,
        endpoint_url=ENDPOINT_URL,
        managed_by=MANAGED_BY_PLATFORM,
        workspace_id=PLATFORM_WORKSPACE_ID,
        created_by="operator",
    )
    model_spec = ModelSpec(
        id=uuid.uuid4(),
        provider_spec_id=spec.id,
        model_name=MODEL_NAME,
        display_name="Test Model mini",
        context_window=128000,
        input_cost_per_token=Decimal("1.5e-7"),
        output_cost_per_token=Decimal("6e-7"),
        workspace_id=PLATFORM_WORKSPACE_ID,
        created_by="operator",
    )
    s.add_all([config, model_spec])
    await s.flush()
    s.add(
        ModelInstance(
            id=platform_instance_id(PROVIDER_KEY, MODEL_NAME),
            provider_config_id=config.id,
            model_spec_id=model_spec.id,
            name="Test Model mini",
            workspace_id=PLATFORM_WORKSPACE_ID,
            created_by="operator",
        )
    )
    await s.commit()


def _ctx(workspace: str) -> UserContext:
    return UserContext(user_id=f"user-of-{workspace}", workspace_id=workspace)


async def test_platform_config_is_visible_from_every_workspace(session):
    """The point of the whole feature: a tenant sees a model they never configured."""
    spec = await _provider_spec(session)
    await _install_platform_model(session, spec)

    for tenant in (TENANT_A, TENANT_B):
        repo = ProviderConfigRepository(session, _ctx(tenant))
        configs = await repo.list_configs()
        assert [c.name for c in configs] == [PLATFORM_CONFIG_NAME], (
            f"{tenant} should see the platform configuration"
        )
        assert configs[0].managed_by == MANAGED_BY_PLATFORM


async def test_one_tenant_still_cannot_see_another_tenants_config(session):
    """The widened read must not have widened anything else."""
    spec = await _provider_spec(session)
    own = ProviderConfig(
        id=uuid.uuid4(),
        provider_spec_id=spec.id,
        name="A's own key",
        workspace_id=TENANT_A,
        created_by="user-of-a",
    )
    session.add(own)
    await session.commit()

    seen_by_b = await ProviderConfigRepository(session, _ctx(TENANT_B)).list_configs()
    assert seen_by_b == [], "tenant B must not see tenant A's configuration"

    seen_by_a = await ProviderConfigRepository(session, _ctx(TENANT_A)).list_configs()
    assert [c.name for c in seen_by_a] == ["A's own key"]


async def test_tenant_cannot_update_or_delete_the_platform_config(session):
    """Visible is not writable — this is what stops a tenant repointing our key."""
    spec = await _provider_spec(session)
    await _install_platform_model(session, spec)

    repo = ProviderConfigRepository(session, _ctx(TENANT_A))
    config = (await repo.list_configs())[0]

    assert await repo.update(config.id, name="hijacked", api_key=TENANT_SECRET_NAME) is None
    assert await repo.delete(config.id) is False

    await session.commit()
    fresh = await session.execute(select(ProviderConfig).where(ProviderConfig.id == config.id))
    row = fresh.scalar_one()
    assert row.name == PLATFORM_CONFIG_NAME, "the platform configuration was modified"
    assert row.api_key == PLATFORM_SECRET_NAME, "the credential reference was repointed"


async def test_tenant_can_still_update_its_own_config(session):
    """The write guard must not have broken ordinary configuration editing."""
    spec = await _provider_spec(session)
    own = ProviderConfig(
        id=uuid.uuid4(),
        provider_spec_id=spec.id,
        name="before",
        workspace_id=TENANT_A,
        created_by="user-of-a",
    )
    session.add(own)
    await session.commit()

    repo = ProviderConfigRepository(session, _ctx(TENANT_A))
    updated = await repo.update(own.id, name="after")
    assert updated is not None and updated.name == "after"
    assert await repo.delete(own.id) is True


async def test_platform_model_instances_are_visible_and_unwritable(session):
    """The instance is what an agent selects, so it has to carry the same rule."""
    spec = await _provider_spec(session)
    await _install_platform_model(session, spec)

    repo = ModelInstanceRepository(session, _ctx(TENANT_B))
    instances = await repo.list_instances()
    assert [i.name for i in instances] == ["Test Model mini"]

    instance_id = instances[0].id
    assert await repo.delete(instance_id) is False
    assert await repo.update(instance_id, name="hijacked") is None


async def test_the_worker_can_resolve_a_platform_model_from_a_tenant_workspace(session):
    """The path an actual run takes, which no other test here exercises.

    Listing the model is what makes it selectable; THIS is what makes it runnable.
    The worker resolves the instance by id under the tenant's own context — not the
    platform's — and reads the provider and model off the loaded relationships to
    decide which workspace's secrets to read and what to send. A widened list with a
    strict get_by_id would look completely healthy right up until someone pressed
    run, and then fail as "model not found" on a model plainly visible in the picker.
    """
    spec = await _provider_spec(session)
    await _install_platform_model(session, spec)

    repo = ModelInstanceRepository(session, _ctx(TENANT_A))
    instance = await repo.get_with_relations(platform_instance_id(PROVIDER_KEY, MODEL_NAME))

    assert instance is not None, "the worker could not resolve the platform model"
    # Everything _resolve_model_info reads, in the order it needs it.
    assert instance.provider_config.provider_spec.provider_type == "openai"
    assert instance.model_spec.model_name == MODEL_NAME
    assert instance.provider_config.endpoint_url == ENDPOINT_URL
    assert instance.model_spec.input_cost_per_token == Decimal("1.5e-7"), (
        "without pricing the run is refused before it starts"
    )
    # The two fields that decide whose secrets are read and whose money is spent.
    assert instance.provider_config.managed_by == MANAGED_BY_PLATFORM
    assert instance.provider_config.api_key == PLATFORM_SECRET_NAME


def test_reject_platform_managed_only_fires_for_platform_rows():
    """A plain object stands in for the row: the check is one attribute, not a query."""

    class _Row:
        name = "x"

        def __init__(self, managed_by):
            self.managed_by = managed_by

    _reject_platform_managed(_Row(None), "modified")
    _reject_platform_managed(_Row("user"), "modified")
    with pytest.raises(PlatformManagedConfigError):
        _reject_platform_managed(_Row(MANAGED_BY_PLATFORM), "modified")


def test_platform_ids_are_pinned_values_not_merely_stable():
    """These ids are a contract with a database this code cannot see.

    A platform model's instance id is what billing's rate cards are keyed on, and
    those rows live in the payments service — a different service, a different
    database, written by hand against these values. The writer that mints them is
    the operator, which is a separate deployable holding its own copy of the recipe.

    So "deterministic" is not enough to assert. Changing the namespace, or the
    string fed into it, would still be deterministic and would still produce stable
    ids — just different ones, matching no rate card, and the only symptom would be
    models running on our provider credit and charging nobody. Nothing would error.

    Hence the literals. If this test fails, the ids changed, and every rate card
    naming them has to change with it in the same deploy.
    """
    assert str(platform_instance_id("openai", "gpt-4o-mini")) == (
        "481a7f8b-1f56-50c9-bae0-615b2a327d4b"
    )
    assert str(platform_config_id("openai")) == "56ee4e48-5db3-5d4b-ade2-3c06b440f4f8"
