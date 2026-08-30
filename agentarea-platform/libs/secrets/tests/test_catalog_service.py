"""Catalog rules, against a real database.

The rules that matter here are enforced by SQL — a unique constraint decides
what "create" means, a RESTRICT foreign key decides what "delete" means — so a
stubbed session would only re-assert what the stub was told. Needs a PostgreSQL
carrying the schema; skips without one.
"""

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from agentarea_common.auth import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets.catalog_service import (
    SURFACED_OWNER_TYPES,
    DuplicateSecretNameError,
    ManagedSecretError,
    SecretCatalogService,
    SecretInUseError,
    SecretNotFoundError,
)
from agentarea_secrets.database_secret_manager import DatabaseSecretManager
from agentarea_secrets.models import EncryptedSecret
from agentarea_secrets.naming import ReservedSecretNameError, SecretNameError
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("SECRETS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="SECRETS_TEST_DATABASE_URL not set; skipping schema-backed catalog tests",
)

WORKSPACE = "catalog-test-ws"
OTHER_WORKSPACE = "catalog-test-other-ws"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.execute(
            text("DELETE FROM secret_references WHERE workspace_id LIKE 'catalog-test-%'")
        )
        await s.execute(
            text("DELETE FROM encrypted_secrets WHERE workspace_id LIKE 'catalog-test-%'")
        )
        await s.commit()
    await engine.dispose()


def _catalog(session: AsyncSession, workspace: str = WORKSPACE) -> SecretCatalogService:
    ctx = UserContext(user_id="tester", workspace_id=workspace)
    manager = DatabaseSecretManager(
        session=session, user_context=ctx, encryption_key=Fernet.generate_key().decode()
    )
    return SecretCatalogService(session=session, user_context=ctx, secret_manager=manager)


class TestCreate:
    async def test_creates_a_user_owned_secret(self, session: AsyncSession) -> None:
        catalog = _catalog(session)
        secret = await catalog.create_user_secret("openai-key", "sk-abcdefgh1234", "For GPT")

        assert secret.secret_name == "openai-key"
        assert secret.description == "For GPT"
        assert secret.owner_type is None
        assert "sk-abcdefgh1234" not in (secret.encrypted_value or "")

    async def test_rejects_a_name_reserved_for_the_platform(self, session: AsyncSession) -> None:
        catalog = _catalog(session)
        with pytest.raises(ReservedSecretNameError):
            await catalog.create_user_secret(
                f"provider_config_{uuid.uuid4()}", "stolen", None
            )

    async def test_rejects_a_malformed_name(self, session: AsyncSession) -> None:
        catalog = _catalog(session)
        with pytest.raises(SecretNameError):
            await catalog.create_user_secret("Has Spaces", "v", None)

    async def test_rejects_a_duplicate_rather_than_overwriting(
        self, session: AsyncSession
    ) -> None:
        # set_secret would have updated the existing row, so a caller asking to
        # create would silently replace a value something else is resolving.
        catalog = _catalog(session)
        await catalog.create_user_secret("dupe-key", "first-value-here", None)
        with pytest.raises(DuplicateSecretNameError):
            await catalog.create_user_secret("dupe-key", "second-value-here", None)


class TestManagedSecretsAreOffLimits:
    async def _managed(self, session: AsyncSession) -> EncryptedSecret:
        secret = EncryptedSecret(
            id=uuid.uuid4(),
            workspace_id=WORKSPACE,
            secret_name=f"provider_config_{uuid.uuid4()}",
            encrypted_value="ciphertext",
            owner_type="provider_config",
            owner_id=str(uuid.uuid4()),
            created_by="platform",
        )
        session.add(secret)
        await session.commit()
        return secret

    async def test_absent_from_the_list(self, session: AsyncSession) -> None:
        await self._managed(session)
        catalog = _catalog(session)
        assert await catalog.list_user_secrets() == []

    async def test_cannot_be_deleted(self, session: AsyncSession) -> None:
        secret = await self._managed(session)
        catalog = _catalog(session)
        with pytest.raises(ManagedSecretError):
            await catalog.delete_user_secret(secret.id)

    async def test_cannot_be_rotated(self, session: AsyncSession) -> None:
        secret = await self._managed(session)
        catalog = _catalog(session)
        with pytest.raises(ManagedSecretError):
            await catalog.rotate_user_secret(secret.id, "attacker-chosen")


class TestVisibleSecrets:
    """What the /secrets page shows.

    Listing only user-created rows told a workspace with a configured MCP
    server it had no secrets at all, while its credentials sat in the same
    table under the connection's ownership.
    """

    async def _owned(self, session: AsyncSession, owner_type: str, name: str) -> EncryptedSecret:
        secret = EncryptedSecret(
            id=uuid.uuid4(),
            workspace_id=WORKSPACE,
            secret_name=name,
            encrypted_value="ciphertext",
            owner_type=owner_type,
            owner_id=str(uuid.uuid4()),
            created_by="platform",
        )
        session.add(secret)
        await session.commit()
        return secret

    async def test_shows_credentials_a_connection_holds(self, session: AsyncSession) -> None:
        catalog = _catalog(session)
        await self._owned(session, "mcp_instance", f"mcp_instance_{uuid.uuid4()}_API_KEY")
        await catalog.create_user_secret("my-own-key", "sk-value-here-1234", None)

        names = {s.secret_name for s in await catalog.list_visible_secrets()}

        assert "my-own-key" in names
        assert any(n.startswith("mcp_instance_") for n in names)

    @pytest.mark.parametrize("owner_type", SURFACED_OWNER_TYPES)
    def test_every_surfaced_owner_is_a_real_producer(self, owner_type: str) -> None:
        # Guards the pairing with naming.py: a type listed here that no producer
        # ever writes would be dead config, and one renamed there would silently
        # vanish from the page.
        produced = {
            "provider_config",
            "mcp_instance",
            "mcp_auth_config",
            "trigger",
            "agent",
            "openapi_connection",
            "task",
        }
        assert owner_type in produced

    async def test_wallet_credentials_are_shown(self, session: AsyncSession) -> None:
        # The user pasted these into the wallet form, same as any other
        # credential — hiding them reproduces the bug this class exists for.
        catalog = _catalog(session)
        await self._owned(session, "agent", f"wallet_creds_{uuid.uuid4()}")
        assert len(await catalog.list_visible_secrets()) == 1

    @pytest.mark.parametrize(
        "owner_type,name",
        [
            ("task", f"task-input/{uuid.uuid4()}/api_token"),
            ("task", f"a2a_push_token:{uuid.uuid4()}:cfg"),
        ],
    )
    async def test_machine_generated_owners_stay_hidden(
        self, session: AsyncSession, owner_type: str, name: str
    ) -> None:
        # These scale with tasks, not with configuration, and would bury
        # everything a user actually set up.
        await self._owned(session, owner_type, name)
        assert await _catalog(session).list_visible_secrets() == []

    async def test_the_write_surface_is_unchanged(self, session: AsyncSession) -> None:
        # Visibility is not permission: surfacing a managed row must not make it
        # editable, or the connection owning it loses its credential from here.
        catalog = _catalog(session)
        secret = await self._owned(session, "mcp_instance", f"mcp_instance_{uuid.uuid4()}_KEY")

        assert secret.secret_name in {s.secret_name for s in await catalog.list_visible_secrets()}
        assert await catalog.list_user_secrets() == []
        with pytest.raises(ManagedSecretError):
            await catalog.rotate_user_secret(secret.id, "attacker-chosen")
        with pytest.raises(ManagedSecretError):
            await catalog.delete_user_secret(secret.id)


class TestWorkspaceIsolation:
    async def test_another_workspace_cannot_see_or_touch_it(
        self, session: AsyncSession
    ) -> None:
        mine = await _catalog(session).create_user_secret("shared-name", "my-value-1234", None)

        theirs = _catalog(session, OTHER_WORKSPACE)
        assert await theirs.list_user_secrets() == []
        with pytest.raises(SecretNotFoundError):
            await theirs.get(mine.id)

    async def test_the_same_name_may_exist_in_both(self, session: AsyncSession) -> None:
        await _catalog(session).create_user_secret("shared-name", "mine-value-1234", None)
        other = await _catalog(session, OTHER_WORKSPACE).create_user_secret(
            "shared-name", "theirs-value-1234", None
        )
        assert other.workspace_id == OTHER_WORKSPACE


class TestDeleteGuard:
    async def test_refuses_while_a_consumer_still_points_at_it(
        self, session: AsyncSession
    ) -> None:
        catalog = _catalog(session)
        secret = await catalog.create_user_secret("in-use-key", "value-goes-here", None)
        consumer_id = str(uuid.uuid4())
        await catalog.add_reference(secret.id, "openapi_connection", consumer_id, "Authorization")

        with pytest.raises(SecretInUseError) as caught:
            await catalog.delete_user_secret(secret.id)

        # The error has to name who, or the user cannot act on it.
        assert any(c.consumer_id == consumer_id for c in caught.value.consumers)

    async def test_allows_deletion_once_the_last_reference_is_gone(
        self, session: AsyncSession
    ) -> None:
        catalog = _catalog(session)
        secret = await catalog.create_user_secret("freed-key", "value-goes-here", None)
        consumer_id = str(uuid.uuid4())
        await catalog.add_reference(secret.id, "openapi_connection", consumer_id, "Authorization")
        await catalog.clear_references("openapi_connection", consumer_id)

        await catalog.delete_user_secret(secret.id)
        with pytest.raises(SecretNotFoundError):
            await catalog.get(secret.id)


class _ExternalBackend(BaseSecretManager):
    """A backend that keeps values outside the catalog, as Infisical does."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def external_ref(self, secret_name: str) -> str:
        return f"stub://vault/{secret_name}"

    async def get_secret(self, secret_name: str) -> str | None:
        return self.values.get(secret_name)

    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        self.values[secret_name] = secret_value

    async def delete_secret(self, secret_name: str) -> bool:
        return self.values.pop(secret_name, None) is not None


class TestExternallyStoredValues:
    """The catalog has to work on a backend that is not the database.

    Only DatabaseSecretManager writes a catalog row as a side effect of storing
    a value. Assuming every backend does that left the whole catalog broken
    under SECRET_MANAGER_TYPE=infisical: create raised after the credential had
    already been written, orphaning it.
    """

    def _catalog(self, session: AsyncSession, backend: _ExternalBackend) -> SecretCatalogService:
        ctx = UserContext(user_id="tester", workspace_id=WORKSPACE)
        return SecretCatalogService(session=session, user_context=ctx, secret_manager=backend)

    async def test_create_records_where_the_value_lives(self, session: AsyncSession) -> None:
        backend = _ExternalBackend()
        catalog = self._catalog(session, backend)

        secret = await catalog.create_user_secret("vault-key", "sk-external-1234", "In the vault")

        assert secret.external_ref == "stub://vault/vault-key"
        assert secret.encrypted_value is None  # the CHECK allows exactly one
        assert secret.description == "In the vault"
        assert backend.values["vault-key"] == "sk-external-1234"

    async def test_created_secret_is_listed(self, session: AsyncSession) -> None:
        backend = _ExternalBackend()
        catalog = self._catalog(session, backend)
        await catalog.create_user_secret("vault-key", "sk-external-1234", None)

        assert [s.secret_name for s in await catalog.list_user_secrets()] == ["vault-key"]

    async def test_delete_removes_the_value_too(self, session: AsyncSession) -> None:
        # Dropping the row is enough only when the row was the value.
        backend = _ExternalBackend()
        catalog = self._catalog(session, backend)
        secret = await catalog.create_user_secret("vault-key", "sk-external-1234", None)

        await catalog.delete_user_secret(secret.id)

        assert "vault-key" not in backend.values

    async def test_rotate_reaches_the_backend(self, session: AsyncSession) -> None:
        backend = _ExternalBackend()
        catalog = self._catalog(session, backend)
        secret = await catalog.create_user_secret("vault-key", "sk-external-1234", None)

        rotated = await catalog.rotate_user_secret(secret.id, "sk-external-9999")

        assert backend.values["vault-key"] == "sk-external-9999"
        # The row still points at the same place; only the value moved.
        assert rotated.external_ref == "stub://vault/vault-key"
        assert rotated.encrypted_value is None


class TestRotate:
    async def test_replaces_the_value_in_place(self, session: AsyncSession) -> None:
        catalog = _catalog(session)
        secret = await catalog.create_user_secret("rotate-me", "old-value-aaaa", None)
        before = secret.encrypted_value

        rotated = await catalog.rotate_user_secret(secret.id, "new-value-bbbb")

        # Same row, new ciphertext: consumers reference the id, so rotating must
        # not mint a different secret out from under them.
        assert rotated.id == secret.id
        assert rotated.encrypted_value != before
        assert await catalog._secrets.get_secret("rotate-me") == "new-value-bbbb"

    async def test_consumers_survive_rotation(self, session: AsyncSession) -> None:
        # Rotation is the reason a reference beats a copied value: whoever
        # points at the secret picks up the new one without being touched.
        catalog = _catalog(session)
        secret = await catalog.create_user_secret("rotate-ref", "old-value-aaaa", None)
        consumer_id = str(uuid.uuid4())
        await catalog.add_reference(secret.id, "openapi_connection", consumer_id, "Authorization")

        await catalog.rotate_user_secret(secret.id, "new-value-bbbb")

        assert [c.consumer_id for c in await catalog.consumers(secret.id)] == [consumer_id]
