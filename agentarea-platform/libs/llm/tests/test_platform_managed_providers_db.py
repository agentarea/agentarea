"""Platform-managed providers, against a real schema.

The rule under test is a visibility rule expressed in SQL — a platform-managed
configuration is readable from every workspace, writable from none — and a mocked
session has no idea what a WHERE clause does. These drive the real repositories
against a migrated database for the same reason the secret-lifecycle tests next
door do: the mocked version of this would pass no matter which way the filter went.

Needs a PostgreSQL migrated to head; skips without one:

    LLM_TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:55471/agentarea_test  # pragma: allowlist secret
"""

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from agentarea_common.auth import UserContext
from agentarea_llm.application.platform_provider_seeder import (
    PLATFORM_WORKSPACE_ID,
    PlatformModel,
    PlatformProvider,
    PlatformProviderSeeder,
    parse_platform_providers,
    platform_config_id,
    platform_instance_id,
    platform_model_instance_ids,
)
from agentarea_llm.application.provider_service import (
    PlatformManagedConfigError,
    _reject_platform_managed,
)
from agentarea_llm.domain.models import MANAGED_BY_PLATFORM, ProviderConfig, ProviderSpec
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("LLM_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="LLM_TEST_DATABASE_URL not set; skipping schema-backed platform provider tests",
)

# Credential REFERENCES, not credentials — the whole point of managed_by is that these
# name where a key lives rather than being one. Named rather than inlined so the
# allowlist pragma sits on a line by itself: ruff reflowed an earlier inline assert
# across two lines and left the pragma on the closing paren, where detect-secrets
# stopped seeing it.
PLATFORM_CREDENTIAL_REF = "platformtest"  # pragma: allowlist secret
TENANT_CREDENTIAL_REF = "tenant-key"  # pragma: allowlist secret

TENANT_A = "platform-test-tenant-a"
TENANT_B = "platform-test-tenant-b"
PROVIDER_KEY = "platform-test-openai"


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


def _ctx(workspace: str) -> UserContext:
    return UserContext(user_id=f"user-of-{workspace}", workspace_id=workspace)


def _declared() -> PlatformProvider:
    return PlatformProvider(
        provider_key=PROVIDER_KEY,
        name="AgentArea (included)",
        credential=PLATFORM_CREDENTIAL_REF,
        endpoint_url="https://llm.example.invalid/v1",
        models=[
            PlatformModel(
                model_name="test-model-mini",
                display_name="Test Model mini",
                context_window=128000,
                input_cost_per_token=1.5e-7,
                output_cost_per_token=6e-7,
            )
        ],
    )


async def test_platform_config_is_visible_from_every_workspace(session):
    """The point of the whole feature: a tenant sees a model they never configured."""
    await _provider_spec(session)
    await PlatformProviderSeeder(session).seed([_declared()])

    for tenant in (TENANT_A, TENANT_B):
        repo = ProviderConfigRepository(session, _ctx(tenant))
        configs = await repo.list_configs()
        assert [c.name for c in configs] == ["AgentArea (included)"], (
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
    await _provider_spec(session)
    await PlatformProviderSeeder(session).seed([_declared()])

    repo = ProviderConfigRepository(session, _ctx(TENANT_A))
    config = (await repo.list_configs())[0]

    assert await repo.update(config.id, name="hijacked", api_key=TENANT_CREDENTIAL_REF) is None
    assert await repo.delete(config.id) is False

    await session.commit()
    fresh = await session.execute(select(ProviderConfig).where(ProviderConfig.id == config.id))
    row = fresh.scalar_one()
    assert row.name == "AgentArea (included)", "the platform configuration was modified"
    assert row.api_key == PLATFORM_CREDENTIAL_REF, "the credential reference was repointed"


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
    await _provider_spec(session)
    await PlatformProviderSeeder(session).seed([_declared()])

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
    decide which credential store to read and what to send. A widened list with a
    strict get_by_id would look completely healthy right up until someone pressed
    run, and then fail as "model not found" on a model plainly visible in the picker.
    """
    await _provider_spec(session)
    await PlatformProviderSeeder(session).seed([_declared()])

    repo = ModelInstanceRepository(session, _ctx(TENANT_A))
    instance = await repo.get_with_relations(platform_instance_id(PROVIDER_KEY, "test-model-mini"))

    assert instance is not None, "the worker could not resolve the platform model"
    # Everything _resolve_model_info reads, in the order it needs it.
    assert instance.provider_config.provider_spec.provider_type == "openai"
    assert instance.model_spec.model_name == "test-model-mini"
    assert instance.provider_config.endpoint_url == "https://llm.example.invalid/v1"
    assert instance.model_spec.input_cost_per_token == 1.5e-7, (
        "without pricing the run is refused before it starts"
    )
    # The two fields that decide whose credential is read and whose money is spent.
    assert instance.provider_config.managed_by == MANAGED_BY_PLATFORM
    assert instance.provider_config.api_key == PLATFORM_CREDENTIAL_REF


async def test_seeding_twice_changes_nothing_and_keeps_ids_stable(session):
    """It runs on every restart and every replica, so converging is the requirement.

    The instance id is what agents store and what billing meters against; a second
    run that minted a new one would silently unlink every agent using the model.
    """
    await _provider_spec(session)
    seeder = PlatformProviderSeeder(session)

    first = await seeder.seed([_declared()])
    ids_after_first = await platform_model_instance_ids(session)

    second = await seeder.seed([_declared()])
    ids_after_second = await platform_model_instance_ids(session)

    assert first == {"providers": 1, "models": 1, "skipped": 0}
    assert second == {"providers": 1, "models": 0, "skipped": 0}, "second run created a model"
    assert ids_after_first == ids_after_second != []


async def test_a_provider_with_no_spec_is_skipped_not_fatal(session):
    """One misconfigured provider must not cost the deployment the others."""
    await _provider_spec(session)
    missing = PlatformProvider(provider_key="no-such-provider-key", name="Nope", models=[])

    summary = await PlatformProviderSeeder(session).seed([missing, _declared()])

    assert summary == {"providers": 1, "models": 1, "skipped": 1}
    assert len(await platform_model_instance_ids(session)) == 1


async def test_seeder_reuses_a_model_spec_a_tenant_created_first(session):
    """uq_model_specs_provider_model is global, so the insert would otherwise fail."""
    from agentarea_llm.domain.models import ModelSpec

    spec = await _provider_spec(session)
    tenant_owned = ModelSpec(
        id=uuid.uuid4(),
        provider_spec_id=spec.id,
        model_name="test-model-mini",
        display_name="Tenant's own naming",
        context_window=8000,
        input_cost_per_token=9.9e-7,
        output_cost_per_token=9.9e-7,
        workspace_id=TENANT_A,
        created_by="user-of-a",
    )
    session.add(tenant_owned)
    await session.commit()

    summary = await PlatformProviderSeeder(session).seed([_declared()])

    assert summary["models"] == 1
    await session.refresh(tenant_owned)
    assert tenant_owned.display_name == "Tenant's own naming", "tenant's spec was overwritten"
    assert tenant_owned.input_cost_per_token == 9.9e-7, "tenant's pricing was overwritten"


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


def test_config_parsing_rejects_a_model_with_no_price():
    """Pricing is required because the runtime refuses to run without it.

    Caught here, at startup, against a named field — rather than as a workflow
    failure hours later reading 'model pricing is not configured'.
    """
    with pytest.raises(ValueError, match="input_cost_per_token"):
        parse_platform_providers(
            [
                {
                    "provider_key": "openai",
                    "models": [{"model_name": "m", "context_window": 1000}],
                }
            ]
        )


def test_config_parsing_accepts_a_full_declaration():
    providers = parse_platform_providers(
        [
            {
                "provider_key": "openai",
                "name": "AgentArea",
                "credential": "openai",
                "models": [
                    {
                        "model_name": "gpt-4o-mini",
                        "context_window": 128000,
                        "input_cost_per_token": 1.5e-7,
                        "output_cost_per_token": 6e-7,
                    }
                ],
            }
        ]
    )
    assert len(providers) == 1
    assert providers[0].credential == "openai"
    # display_name defaults to the model name rather than being left empty, so a
    # minimal declaration still produces something a user can read in a list.
    assert providers[0].models[0].display_name == "gpt-4o-mini"


def test_no_declaration_is_not_an_error():
    """The open build's normal state: supplies no keys, offers no keyless models."""
    assert parse_platform_providers(None) == []
    assert parse_platform_providers([]) == []


def test_platform_ids_are_pinned_values_not_merely_stable():
    """These ids are a contract with a database this code cannot see.

    A platform model's instance id is what billing's rate cards are keyed on, and
    those rows live in the payments service — a different service, a different
    database, written by a migration that hardcodes these values.

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


async def test_seeded_instance_carries_the_derived_id(session):
    """The value above must be the id the row actually gets, not just what a helper returns."""
    await _provider_spec(session)
    await PlatformProviderSeeder(session).seed([_declared()])

    instances = await ModelInstanceRepository(session, _ctx(TENANT_A)).list_instances()
    assert [i.id for i in instances] == [platform_instance_id(PROVIDER_KEY, "test-model-mini")]
