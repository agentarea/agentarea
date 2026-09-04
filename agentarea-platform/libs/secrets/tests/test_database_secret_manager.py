"""Unit tests for DatabaseSecretManager.

Tests encryption, decryption, CRUD operations, and error handling.
"""

import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_secrets.database_secret_manager import DatabaseSecretManager, EncryptedSecret
from cryptography.fernet import Fernet


class TestDatabaseSecretManager:
    """Unit tests for DatabaseSecretManager."""

    def test_init_with_provided_key(self, mock_db_session, test_user_context, encryption_key):
        """Test initialization with provided encryption key."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        assert manager.session == mock_db_session
        assert manager.user_context == test_user_context
        assert manager.workspace_id == "test-workspace-456"
        assert manager._fernet is not None

    def test_init_ignores_environment_key(self, mock_db_session, test_user_context):
        """DatabaseSecretManager accepts its key only from the factory."""
        env_key = Fernet.generate_key().decode("utf-8")

        with (
            patch.dict("os.environ", {"SECRET_MANAGER_ENCRYPTION_KEY": env_key}),
            pytest.raises(ValueError, match="Encryption key is required"),
        ):
            DatabaseSecretManager(
                session=mock_db_session,
                user_context=test_user_context,
            )

    def test_init_fails_without_key(self, mock_db_session, test_user_context):
        """Test initialization fails when no encryption key is provided."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Encryption key is required"):
                DatabaseSecretManager(
                    session=mock_db_session,
                    user_context=test_user_context,
                )

    def test_encrypt_decrypt_roundtrip(self, mock_db_session, test_user_context, encryption_key):
        """Test encryption and decryption work correctly."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        secret_value = "my-super-secret-api-key"  # noqa: S105 - test fixture
        encrypted = manager._encrypt(secret_value)

        # Encrypted value should be different from original
        assert encrypted != secret_value

        # Decryption should recover original value
        decrypted = manager._decrypt(encrypted)
        assert decrypted == secret_value

    def test_decrypt_with_wrong_key_raises_error(self, mock_db_session, test_user_context):
        """Test decrypting with wrong key raises ValueError."""
        key1 = Fernet.generate_key().decode("utf-8")
        key2 = Fernet.generate_key().decode("utf-8")

        manager1 = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=key1,
        )

        manager2 = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=key2,
        )

        encrypted = manager1._encrypt("secret")

        with pytest.raises(ValueError, match="Failed to decrypt secret"):
            manager2._decrypt(encrypted)

    def test_decrypt_does_not_log_exception_contents(
        self, mock_db_session, test_user_context, encryption_key, caplog
    ):
        """Decrypt failures must not expose sensitive exception details in logs."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )
        sensitive_error = f"private-{uuid4()}"

        with (
            caplog.at_level(logging.ERROR, logger="agentarea_secrets.database_secret_manager"),
            patch.object(manager._fernet, "decrypt", side_effect=RuntimeError(sensitive_error)),
            pytest.raises(ValueError, match="Failed to decrypt secret"),
        ):
            manager._decrypt("ciphertext")

        assert sensitive_error not in caplog.text

    @pytest.mark.asyncio
    async def test_get_secret_found(self, mock_db_session, test_user_context, encryption_key):
        """Test getting a secret that exists."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database result
        encrypted_value = manager._encrypt("my-api-key")
        mock_secret = EncryptedSecret(
            workspace_id="test-workspace-456",
            secret_name="openai_api_key",  # noqa: S106 - test fixture
            encrypted_value=encrypted_value,
            created_by="test-user-123",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_secret
        mock_db_session.execute.return_value = mock_result

        # Test
        result = await manager.get_secret("openai_api_key")

        assert result == "my-api-key"
        mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_secret_not_found(self, mock_db_session, test_user_context, encryption_key):
        """Test getting a secret that doesn't exist."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database result - no secret found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        # Test
        result = await manager.get_secret("nonexistent_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_secret_does_not_log_secret_identifier(
        self, mock_db_session, test_user_context, encryption_key, caplog
    ):
        """Reading a missing secret must not reveal its identifier in logs."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result
        secret_name = f"private-{uuid4()}"

        with caplog.at_level(logging.DEBUG, logger="agentarea_secrets.database_secret_manager"):
            assert await manager.get_secret(secret_name) is None

        assert secret_name not in caplog.text

    @pytest.mark.asyncio
    async def test_get_secret_does_not_log_exception_contents(
        self, mock_db_session, test_user_context, encryption_key, caplog
    ):
        """Read failures must not expose sensitive exception details in logs."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )
        sensitive_error = f"private-{uuid4()}"
        mock_db_session.execute.side_effect = Exception(sensitive_error)

        with caplog.at_level(logging.ERROR, logger="agentarea_secrets.database_secret_manager"):
            with pytest.raises(Exception, match=sensitive_error):
                await manager.get_secret("secret-name")

        assert sensitive_error not in caplog.text

    @pytest.mark.asyncio
    async def test_has_secret_found(self, mock_db_session, test_user_context, encryption_key):
        """A stored secret reports as present."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid4()
        mock_db_session.execute.return_value = mock_result

        assert await manager.has_secret("openai_api_key") is True

    @pytest.mark.asyncio
    async def test_has_secret_not_found(self, mock_db_session, test_user_context, encryption_key):
        """A name with no row reports as absent."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        assert await manager.has_secret("nonexistent_key") is False

    @pytest.mark.asyncio
    async def test_has_secret_does_not_decrypt(self, mock_db_session, test_user_context):
        """A value this key cannot open is still a value that exists.

        A rotated ``SECRET_MANAGER_ENCRYPTION_KEY`` leaves rows behind that no
        longer decrypt. Callers that only want to know whether a credential is
        configured must get an answer, not the read failure.
        """
        written_with = Fernet.generate_key().decode("utf-8")
        read_with = Fernet.generate_key().decode("utf-8")

        author = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=written_with,
        )
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=read_with,
        )

        stale_secret = EncryptedSecret(
            workspace_id="test-workspace-456",
            secret_name="channel_cred:telegram:trigger-1",  # noqa: S106 - test fixture
            encrypted_value=author._encrypt("bot-token"),
            created_by="test-user-123",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stale_secret
        mock_db_session.execute.return_value = mock_result

        assert await manager.has_secret(stale_secret.secret_name) is True

        # The value itself is genuinely unreadable — that has not been papered over.
        with pytest.raises(ValueError, match="Failed to decrypt secret"):
            await manager.get_secret(stale_secret.secret_name)

    @pytest.mark.asyncio
    async def test_has_secret_does_not_log_secret_identifier(
        self, mock_db_session, test_user_context, encryption_key, caplog
    ):
        """Checking for a missing secret must not reveal its identifier in logs."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )
        mock_db_session.execute.side_effect = Exception("boom")
        secret_name = f"private-{uuid4()}"

        with caplog.at_level(logging.ERROR, logger="agentarea_secrets.database_secret_manager"):
            with pytest.raises(Exception, match="boom"):
                await manager.has_secret(secret_name)

        assert secret_name not in caplog.text

    @pytest.mark.asyncio
    async def test_set_secret_creates_new(self, mock_db_session, test_user_context, encryption_key):
        """Test setting a secret that doesn't exist (create)."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database - secret doesn't exist
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        # Test
        await manager.set_secret("new_secret", "secret-value")

        # Verify session.add was called
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()

        # Verify the secret object added
        added_secret = mock_db_session.add.call_args[0][0]
        assert isinstance(added_secret, EncryptedSecret)
        assert added_secret.workspace_id == "test-workspace-456"
        assert added_secret.secret_name == "new_secret"  # noqa: S105 - test fixture
        assert added_secret.created_by == "test-user-123"
        # Verify it's encrypted
        decrypted = manager._decrypt(added_secret.encrypted_value)
        assert decrypted == "secret-value"

    @pytest.mark.asyncio
    async def test_set_secret_does_not_log_secret_name(
        self, mock_db_session, test_user_context, encryption_key, caplog
    ):
        """Secret names must not be emitted to application logs."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result
        secret_name = f"private-{uuid4()}"

        with caplog.at_level(logging.INFO, logger="agentarea_secrets.database_secret_manager"):
            await manager.set_secret(secret_name, "secret-value")

        assert secret_name not in caplog.text

    @pytest.mark.asyncio
    async def test_set_secret_does_not_log_exception_contents(
        self, mock_db_session, test_user_context, encryption_key, caplog
    ):
        """Database errors must not expose sensitive exception details in logs."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )
        secret_value = f"private-{uuid4()}"
        mock_db_session.execute.side_effect = Exception(secret_value)

        with caplog.at_level(logging.ERROR, logger="agentarea_secrets.database_secret_manager"):
            with pytest.raises(Exception, match=secret_value):
                await manager.set_secret("secret-name", secret_value)

        assert secret_value not in caplog.text

    @pytest.mark.asyncio
    async def test_set_secret_updates_existing(
        self, mock_db_session, test_user_context, encryption_key
    ):
        """Test setting a secret that already exists (update)."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database - secret exists
        existing_secret = EncryptedSecret(
            workspace_id="test-workspace-456",
            secret_name="existing_secret",  # noqa: S106 - test fixture
            encrypted_value=manager._encrypt("old-value"),
            created_by="test-user-123",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_secret
        mock_db_session.execute.return_value = mock_result

        # Test
        await manager.set_secret("existing_secret", "new-value")

        # Verify update was called (execute called twice: once for select, once for update)
        assert mock_db_session.execute.call_count == 2
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_secret_rollback_on_error(
        self, mock_db_session, test_user_context, encryption_key
    ):
        """Test that set_secret rolls back on error."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database error
        mock_db_session.execute.side_effect = Exception("Database error")

        # Test
        with pytest.raises(Exception, match="Database error"):
            await manager.set_secret("test_secret", "value")

        mock_db_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_secret_exists(self, mock_db_session, test_user_context, encryption_key):
        """Test deleting a secret that exists."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database - secret exists
        mock_secret = EncryptedSecret(
            workspace_id="test-workspace-456",
            secret_name="to_delete",  # noqa: S106 - test fixture
            encrypted_value=manager._encrypt("value"),
            created_by="test-user-123",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_secret
        mock_db_session.execute.return_value = mock_result

        # Test
        result = await manager.delete_secret("to_delete")

        assert result is True
        mock_db_session.delete.assert_called_once_with(mock_secret)
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_secret_not_exists(
        self, mock_db_session, test_user_context, encryption_key
    ):
        """Test deleting a secret that doesn't exist."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database - secret doesn't exist
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        # Test
        result = await manager.delete_secret("nonexistent")

        assert result is False
        mock_db_session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_secret_does_not_log_secret_identifier(
        self, mock_db_session, test_user_context, encryption_key, caplog
    ):
        """Deleting a missing secret must not reveal its identifier in logs."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result
        secret_name = f"private-{uuid4()}"

        with caplog.at_level(logging.DEBUG, logger="agentarea_secrets.database_secret_manager"):
            assert await manager.delete_secret(secret_name) is False

        assert secret_name not in caplog.text

    @pytest.mark.asyncio
    async def test_delete_secret_does_not_log_exception_contents(
        self, mock_db_session, test_user_context, encryption_key, caplog
    ):
        """Delete failures must not expose sensitive exception details in logs."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )
        sensitive_error = f"private-{uuid4()}"
        mock_db_session.execute.side_effect = Exception(sensitive_error)

        with caplog.at_level(logging.ERROR, logger="agentarea_secrets.database_secret_manager"):
            with pytest.raises(Exception, match=sensitive_error):
                await manager.delete_secret("secret-name")

        assert sensitive_error not in caplog.text

    @pytest.mark.asyncio
    async def test_delete_secret_rollback_on_error(
        self, mock_db_session, test_user_context, encryption_key
    ):
        """Test that delete_secret rolls back on error."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database error
        mock_db_session.execute.side_effect = Exception("Database error")

        # Test
        with pytest.raises(Exception, match="Database error"):
            await manager.delete_secret("test_secret")

        mock_db_session.rollback.assert_called_once()

    def test_workspace_isolation(self, mock_db_session, encryption_key):
        """Test that secrets are scoped to workspace."""
        from agentarea_common.auth import UserContext

        user_context_1 = UserContext(
            user_id="user-1",
            workspace_id="workspace-1",
        )
        user_context_2 = UserContext(
            user_id="user-2",
            workspace_id="workspace-2",
        )

        manager_1 = DatabaseSecretManager(
            session=mock_db_session,
            user_context=user_context_1,
            encryption_key=encryption_key,
        )
        manager_2 = DatabaseSecretManager(
            session=mock_db_session,
            user_context=user_context_2,
            encryption_key=encryption_key,
        )

        assert manager_1.workspace_id == "workspace-1"
        assert manager_2.workspace_id == "workspace-2"
        assert manager_1.workspace_id != manager_2.workspace_id
