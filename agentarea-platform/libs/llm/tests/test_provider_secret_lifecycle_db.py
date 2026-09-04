"""Provider-config secret lifecycle, against a real schema.

These run the service's real SQL against a database carrying the migrated
schema, and that is the whole point: the rule they check — a secret cannot be
deleted while `provider_configs.api_key_secret_id` or a `secret_references` row
still holds a RESTRICT foreign key to it — lives in the constraints, not in
Python. The unit tests next door drive a mocked session, which has no foreign
keys, so they passed while deleting any provider config that owned its API key
returned 500.

Needs a PostgreSQL migrated to head; skips without one:

    SECRETS_TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:55441/agentarea_test
"""

import os
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth import UserContext
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.domain.models import ProviderConfig, ProviderSpec
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from agentarea_llm.schemas.dto import ProviderConfigUpdate
from agentarea_secrets.database_secret_manager import DatabaseSecretManager
from agentarea_secrets.models import EncryptedSecret, SecretReference
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("SECRETS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="SECRETS_TEST_DATABASE_URL not set; skipping schema-backed provider secret tests",
)

WORKSPACE = "provider-secret-test-ws"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
        for table in ("secret_references", "provider_configs", "provider_specs"):
            await s.execute(text(f"DELETE FROM {table} WHERE workspace_id = :w"), {"w": WORKSPACE})
        await s.execute(
            text("DELETE FROM encrypted_secrets WHERE workspace_id = :w"), {"w": WORKSPACE}
        )
        await s.commit()
    await engine.dispose()


def _service(session: AsyncSession) -> ProviderService:
    ctx = UserContext(user_id="tester", workspace_id=WORKSPACE)
    return ProviderService(
        provider_spec_repo=ProviderSpecRepository(session, ctx),
        provider_config_repo=ProviderConfigRepository(session, ctx),
        model_spec_repo=ModelSpecRepository(session, ctx),
        model_instance_repo=ModelInstanceRepository(session, ctx),
        event_broker=AsyncMock(),
        secret_manager=DatabaseSecretManager(
            session=session, user_context=ctx, encryption_key=Fernet.generate_key().decode()
        ),
    )


async def _spec(session: AsyncSession) -> ProviderSpec:
    spec = ProviderSpec(
        id=uuid.uuid4(),
        provider_key=f"k-{uuid.uuid4().hex[:8]}",
        name="Test provider",
        provider_type="openai",
        is_builtin=False,
        workspace_id=WORKSPACE,
        created_by="tester",
    )
    session.add(spec)
    await session.commit()
    return spec


async def _config_owning_its_key(session: AsyncSession, service: ProviderService) -> ProviderConfig:
    """A config holding a `provider_config_{id}` secret it minted for itself."""
    spec = await _spec(session)
    config_id = uuid.uuid4()
    secret_name = f"provider_config_{config_id}"
    await service.secret_manager.set_secret(secret_name, "sk-lives-here-1234")
    secret_id = (
        await session.execute(
            select(EncryptedSecret.id).where(
                EncryptedSecret.workspace_id == WORKSPACE,
                EncryptedSecret.secret_name == secret_name,
            )
        )
    ).scalar_one()

    config = ProviderConfig(
        id=config_id,
        provider_spec_id=spec.id,
        name="cfg",
        api_key=secret_name,
        api_key_secret_id=secret_id,
        workspace_id=WORKSPACE,
        created_by="tester",
    )
    session.add(config)
    session.add(
        SecretReference(
            workspace_id=WORKSPACE,
            secret_id=secret_id,
            consumer_type="provider_config",
            consumer_id=str(config_id),
            field="api_key",
        )
    )
    await session.commit()
    return config


async def test_deleting_a_config_that_owns_its_key_succeeds(session: AsyncSession) -> None:
    service = _service(session)
    config = await _config_owning_its_key(session, service)

    assert await service.delete_provider_config(config.id) is True

    left = (
        await session.execute(
            select(EncryptedSecret).where(
                EncryptedSecret.workspace_id == WORKSPACE,
                EncryptedSecret.secret_name == f"provider_config_{config.id}",
            )
        )
    ).scalar_one_or_none()
    assert left is None, "the config's own secret should go with it"


async def test_clearing_the_api_key_succeeds(session: AsyncSession) -> None:
    service = _service(session)
    config = await _config_owning_its_key(session, service)

    updated = await service.update_provider_config(config.id, ProviderConfigUpdate(api_key=""))

    assert updated is not None
    assert updated.api_key is None
    assert updated.api_key_secret_id is None


async def test_repointing_at_a_user_secret_drops_the_configs_own_one(
    session: AsyncSession,
) -> None:
    service = _service(session)
    config = await _config_owning_its_key(session, service)

    await service.secret_manager.set_secret("shared-openai-key", "sk-shared-value-1234")
    shared_id = (
        await session.execute(
            select(EncryptedSecret.id).where(
                EncryptedSecret.workspace_id == WORKSPACE,
                EncryptedSecret.secret_name == "shared-openai-key",
            )
        )
    ).scalar_one()

    updated = await service.update_provider_config(
        config.id, ProviderConfigUpdate(api_key_secret_id=shared_id)
    )

    assert updated is not None
    assert updated.api_key == "shared-openai-key"
    assert updated.api_key_secret_id == shared_id

    # The borrowed secret survives; the abandoned own-secret does not.
    assert (
        await session.execute(
            select(EncryptedSecret).where(EncryptedSecret.id == shared_id)
        )
    ).scalar_one_or_none() is not None
    assert (
        await session.execute(
            select(EncryptedSecret).where(
                EncryptedSecret.secret_name == f"provider_config_{config.id}",
                EncryptedSecret.workspace_id == WORKSPACE,
            )
        )
    ).scalar_one_or_none() is None


async def test_deleting_a_config_leaves_a_borrowed_secret_alone(session: AsyncSession) -> None:
    """A shared secret belongs to the user, not to whichever config points at it."""
    service = _service(session)
    spec = await _spec(session)

    await service.secret_manager.set_secret("borrowed-key", "sk-borrowed-value-1234")
    secret_id = (
        await session.execute(
            select(EncryptedSecret.id).where(
                EncryptedSecret.workspace_id == WORKSPACE,
                EncryptedSecret.secret_name == "borrowed-key",
            )
        )
    ).scalar_one()

    config_id = uuid.uuid4()
    session.add(
        ProviderConfig(
            id=config_id,
            provider_spec_id=spec.id,
            name="borrower",
            api_key="borrowed-key",
            api_key_secret_id=secret_id,
            workspace_id=WORKSPACE,
            created_by="tester",
        )
    )
    session.add(
        SecretReference(
            workspace_id=WORKSPACE,
            secret_id=secret_id,
            consumer_type="provider_config",
            consumer_id=str(config_id),
            field="api_key",
        )
    )
    await session.commit()

    assert await service.delete_provider_config(config_id) is True
    assert (
        await session.execute(
            select(EncryptedSecret).where(EncryptedSecret.id == secret_id)
        )
    ).scalar_one_or_none() is not None
