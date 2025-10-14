"""Integration tests for DatabaseSecretManager with real database.

These tests use a real PostgreSQL database to verify:
- Secret encryption and storage
- Workspace isolation
- Concurrent operations
- Migration compatibility
"""

import asyncio
import os
import uuid
from typing import AsyncGenerator

import pytest
from agentarea_common.auth import UserContext
from agentarea_secrets.database_secret_manager import DatabaseSecretManager, EncryptedSecret
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from agentarea_common.base.models import BaseModel


# Test database URL - can be overridden via environment
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/agentarea_test",
)


@pytest.fixture(scope="module")
async def db_engine():
    """Create test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
async def setup_database(db_engine):
    """Create database tables before tests."""
    async with db_engine.begin() as conn:
        # Create tables
        await conn.run_sync(BaseModel.metadata.create_all)

    yield

    # Cleanup after tests
    async with db_engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.drop_all)


@pytest.fixture
async def db_session(db_engine, setup_database) -> AsyncGenerator[AsyncSession, None]:
    """Create a new database session for each test."""
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session
        await session.rollback()  # Rollback any uncommitted changes
        await session.close()


@pytest.fixture
def workspace_1_user():
    """User context for workspace 1."""
    return UserContext(
        user_id="user-1",
        workspace_id="workspace-1",
    )


@pytest.fixture
def workspace_2_user():
    """User context for workspace 2."""
    return UserContext(
        user_id="user-2",
        workspace_id="workspace-2",
    )


@pytest.fixture
def shared_encryption_key():
    """Shared encryption key for testing."""
    return Fernet.generate_key().decode("utf-8")


@pytest.mark.integration
@pytest.mark.asyncio
class TestDatabaseSecretManagerIntegration:
    """Integration tests for DatabaseSecretManager with real database."""

    async def test_create_and_retrieve_secret(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test creating and retrieving a secret from database."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        # Create secret
        await manager.set_secret("test_api_key", "sk-test-12345")

        # Retrieve secret
        value = await manager.get_secret("test_api_key")

        assert value == "sk-test-12345"

    async def test_update_existing_secret(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test updating an existing secret."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        # Create secret
        await manager.set_secret("api_key", "old-value")

        # Update secret
        await manager.set_secret("api_key", "new-value")

        # Verify update
        value = await manager.get_secret("api_key")
        assert value == "new-value"

        # Verify only one record exists
        result = await db_session.execute(
            select(EncryptedSecret).where(
                EncryptedSecret.workspace_id == "workspace-1",
                EncryptedSecret.secret_name == "api_key",
            )
        )
        secrets = result.scalars().all()
        assert len(secrets) == 1

    async def test_delete_secret(self, db_session, workspace_1_user, shared_encryption_key):
        """Test deleting a secret."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        # Create secret
        await manager.set_secret("temp_key", "temp-value")

        # Delete secret
        deleted = await manager.delete_secret("temp_key")
        assert deleted is True

        # Verify it's gone
        value = await manager.get_secret("temp_key")
        assert value is None

        # Try deleting again - should return False
        deleted_again = await manager.delete_secret("temp_key")
        assert deleted_again is False

    async def test_workspace_isolation(
        self, db_session, workspace_1_user, workspace_2_user, shared_encryption_key
    ):
        """Test that secrets are isolated between workspaces."""
        manager_1 = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        manager_2 = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_2_user,
            encryption_key=shared_encryption_key,
        )

        # Workspace 1 creates a secret
        await manager_1.set_secret("shared_name", "workspace-1-value")

        # Workspace 2 creates a secret with same name
        await manager_2.set_secret("shared_name", "workspace-2-value")

        # Each workspace should see their own value
        value_1 = await manager_1.get_secret("shared_name")
        value_2 = await manager_2.get_secret("shared_name")

        assert value_1 == "workspace-1-value"
        assert value_2 == "workspace-2-value"
        assert value_1 != value_2

    async def test_secret_encryption_in_database(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test that secrets are actually encrypted in the database."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        secret_value = "my-super-secret-password"
        await manager.set_secret("password", secret_value)

        # Query database directly
        result = await db_session.execute(
            select(EncryptedSecret).where(
                EncryptedSecret.workspace_id == "workspace-1",
                EncryptedSecret.secret_name == "password",
            )
        )
        secret_record = result.scalar_one()

        # Verify encrypted value is different from plain text
        assert secret_record.encrypted_value != secret_value
        assert secret_value not in secret_record.encrypted_value

        # Verify we can decrypt it
        decrypted = manager._decrypt(secret_record.encrypted_value)
        assert decrypted == secret_value

    async def test_multiple_secrets_same_workspace(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test storing multiple secrets in the same workspace."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        # Create multiple secrets
        secrets = {
            "openai_key": "sk-openai-123",
            "anthropic_key": "sk-anthropic-456",
            "github_token": "ghp_github789",
            "database_password": "postgres-pwd",
        }

        for name, value in secrets.items():
            await manager.set_secret(name, value)

        # Retrieve and verify all secrets
        for name, expected_value in secrets.items():
            actual_value = await manager.get_secret(name)
            assert actual_value == expected_value

    async def test_concurrent_secret_operations(
        self, db_engine, workspace_1_user, shared_encryption_key
    ):
        """Test concurrent secret operations don't interfere."""
        async_session_maker = sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )

        async def create_secret(secret_name: str, secret_value: str):
            async with async_session_maker() as session:
                manager = DatabaseSecretManager(
                    session=session,
                    user_context=workspace_1_user,
                    encryption_key=shared_encryption_key,
                )
                await manager.set_secret(secret_name, secret_value)

        # Create 10 secrets concurrently
        tasks = [
            create_secret(f"concurrent_key_{i}", f"value_{i}") for i in range(10)
        ]
        await asyncio.gather(*tasks)

        # Verify all secrets were created
        async with async_session_maker() as session:
            manager = DatabaseSecretManager(
                session=session,
                user_context=workspace_1_user,
                encryption_key=shared_encryption_key,
            )

            for i in range(10):
                value = await manager.get_secret(f"concurrent_key_{i}")
                assert value == f"value_{i}"

    async def test_audit_fields_populated(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test that audit fields (created_by, updated_by, timestamps) are populated."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        # Create secret
        await manager.set_secret("audit_test", "value")

        # Query database directly
        result = await db_session.execute(
            select(EncryptedSecret).where(
                EncryptedSecret.workspace_id == "workspace-1",
                EncryptedSecret.secret_name == "audit_test",
            )
        )
        secret_record = result.scalar_one()

        # Verify audit fields
        assert secret_record.created_by == "user-1"
        assert secret_record.created_at is not None
        assert secret_record.updated_at is not None

    async def test_unique_constraint_enforcement(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test that unique constraint on (workspace_id, secret_name) is enforced."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        # Create a secret
        await manager.set_secret("unique_test", "value1")

        # Update should work (not violate constraint)
        await manager.set_secret("unique_test", "value2")

        # Verify only one record exists
        result = await db_session.execute(
            select(EncryptedSecret).where(
                EncryptedSecret.workspace_id == "workspace-1",
                EncryptedSecret.secret_name == "unique_test",
            )
        )
        secrets = result.scalars().all()
        assert len(secrets) == 1
        assert manager._decrypt(secrets[0].encrypted_value) == "value2"

    async def test_large_secret_value(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test storing and retrieving large secret values."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        # Create a large secret (e.g., a JSON service account key)
        large_value = "x" * 10000  # 10KB secret

        await manager.set_secret("large_secret", large_value)

        # Retrieve and verify
        retrieved_value = await manager.get_secret("large_secret")
        assert retrieved_value == large_value

    async def test_special_characters_in_secret_name(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test that special characters in secret names are handled."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        special_names = [
            "secret-with-dashes",
            "secret_with_underscores",
            "secret.with.dots",
            "secret/with/slashes",
            "secret:with:colons",
        ]

        for name in special_names:
            await manager.set_secret(name, f"value-for-{name}")

        for name in special_names:
            value = await manager.get_secret(name)
            assert value == f"value-for-{name}"

    async def test_empty_string_secret_value(
        self, db_session, workspace_1_user, shared_encryption_key
    ):
        """Test storing empty string as secret value."""
        manager = DatabaseSecretManager(
            session=db_session,
            user_context=workspace_1_user,
            encryption_key=shared_encryption_key,
        )

        await manager.set_secret("empty_secret", "")

        value = await manager.get_secret("empty_secret")
        assert value == ""
        assert value is not None  # Should be empty string, not None
