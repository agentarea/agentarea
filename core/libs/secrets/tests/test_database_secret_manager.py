"""Unit tests for DatabaseSecretManager.

Tests encryption, decryption, CRUD operations, and error handling.
"""

import pytest
from agentarea_secrets.database_secret_manager import DatabaseSecretManager, EncryptedSecret
from cryptography.fernet import Fernet
from sqlalchemy import select
from unittest.mock import AsyncMock, MagicMock, patch


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

    @patch.dict("os.environ", {"SECRET_MANAGER_ENCRYPTION_KEY": "test-key-from-env"})
    def test_init_with_env_key(self, mock_db_session, test_user_context):
        """Test initialization with encryption key from environment."""
        # Generate a valid Fernet key for env
        env_key = Fernet.generate_key().decode("utf-8")

        with patch.dict("os.environ", {"SECRET_MANAGER_ENCRYPTION_KEY": env_key}):
            manager = DatabaseSecretManager(
                session=mock_db_session,
                user_context=test_user_context,
            )

            assert manager._fernet is not None

    def test_init_fails_without_key(self, mock_db_session, test_user_context):
        """Test initialization fails when no encryption key is provided."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="SECRET_MANAGER_ENCRYPTION_KEY"):
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

        secret_value = "my-super-secret-api-key"
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
            secret_name="openai_api_key",
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
        assert added_secret.secret_name == "new_secret"
        assert added_secret.created_by == "test-user-123"
        # Verify it's encrypted
        decrypted = manager._decrypt(added_secret.encrypted_value)
        assert decrypted == "secret-value"

    @pytest.mark.asyncio
    async def test_set_secret_updates_existing(self, mock_db_session, test_user_context, encryption_key):
        """Test setting a secret that already exists (update)."""
        manager = DatabaseSecretManager(
            session=mock_db_session,
            user_context=test_user_context,
            encryption_key=encryption_key,
        )

        # Mock database - secret exists
        existing_secret = EncryptedSecret(
            workspace_id="test-workspace-456",
            secret_name="existing_secret",
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
    async def test_set_secret_rollback_on_error(self, mock_db_session, test_user_context, encryption_key):
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
            secret_name="to_delete",
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
    async def test_delete_secret_not_exists(self, mock_db_session, test_user_context, encryption_key):
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
    async def test_delete_secret_rollback_on_error(self, mock_db_session, test_user_context, encryption_key):
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
