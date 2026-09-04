"""Unit tests for SecretManagerFactory class.

Tests the factory pattern implementation with proper settings usage.
"""

from unittest.mock import patch

import pytest
from agentarea_common.config.secrets import SecretManagerSettings
from agentarea_secrets import SecretManagerFactory
from agentarea_secrets.database_secret_manager import DatabaseSecretManager
from agentarea_secrets.infisical_secret_manager import InfisicalSecretManager


class TestSecretManagerFactory:
    """Unit tests for SecretManagerFactory class."""

    def test_factory_initialization_database(self):
        """Test factory initialization with database settings."""
        settings = SecretManagerSettings(SECRET_MANAGER_TYPE="database")
        factory = SecretManagerFactory(settings)

        assert factory.settings.SECRET_MANAGER_TYPE == "database"

    def test_factory_initialization_infisical(self):
        """Test factory initialization with infisical settings."""
        settings = SecretManagerSettings(
            SECRET_MANAGER_TYPE="infisical",
            SECRET_MANAGER_ACCESS_KEY="test-key",
            SECRET_MANAGER_SECRET_KEY="test-secret",
            SECRET_MANAGER_PROJECT_ID="proj-1",
        )
        factory = SecretManagerFactory(settings)

        assert factory.settings.SECRET_MANAGER_TYPE == "infisical"

    def test_create_database_secret_manager(self, mock_db_session, test_user_context):
        """Test creating database secret manager with factory."""
        settings = SecretManagerSettings(SECRET_MANAGER_TYPE="database")
        factory = SecretManagerFactory(settings)

        manager = factory.create(session=mock_db_session, user_context=test_user_context)

        assert isinstance(manager, DatabaseSecretManager)
        assert manager.session == mock_db_session
        assert manager.user_context == test_user_context
        assert manager.workspace_id == "test-workspace-456"

    def test_create_database_with_custom_encryption_key(self, mock_db_session, test_user_context):
        """Test creating database secret manager with custom encryption key."""
        from cryptography.fernet import Fernet

        custom_key = Fernet.generate_key().decode("utf-8")
        settings = SecretManagerSettings(
            SECRET_MANAGER_TYPE="database", SECRET_MANAGER_ENCRYPTION_KEY=custom_key
        )
        factory = SecretManagerFactory(settings)

        manager = factory.create(session=mock_db_session, user_context=test_user_context)

        assert isinstance(manager, DatabaseSecretManager)
        assert manager._fernet is not None

    @patch("infisical_sdk.client.InfisicalSDKClient")
    def test_create_infisical_secret_manager(self, mock_infisical_client, mock_db_session, test_user_context):
        """Test creating Infisical secret manager with factory."""
        settings = SecretManagerSettings(
            SECRET_MANAGER_TYPE="infisical",
            SECRET_MANAGER_ENDPOINT="https://test.infisical.com",
            SECRET_MANAGER_ACCESS_KEY="test-client-id",
            SECRET_MANAGER_SECRET_KEY="test-client-secret",
            SECRET_MANAGER_PROJECT_ID="proj-1",
        )
        factory = SecretManagerFactory(settings)

        manager = factory.create(session=mock_db_session, user_context=test_user_context)

        assert isinstance(manager, InfisicalSecretManager)
        mock_infisical_client.assert_called_once_with(
            host="https://test.infisical.com",
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

    @patch("infisical_sdk.client.InfisicalSDKClient")
    def test_create_infisical_default_endpoint(self, mock_infisical_client, mock_db_session, test_user_context):
        """Test Infisical with default endpoint when not specified."""
        settings = SecretManagerSettings(
            SECRET_MANAGER_TYPE="infisical",
            SECRET_MANAGER_ACCESS_KEY="test-id",
            SECRET_MANAGER_SECRET_KEY="test-secret",
            SECRET_MANAGER_PROJECT_ID="proj-1",
        )
        factory = SecretManagerFactory(settings)

        manager = factory.create(session=mock_db_session, user_context=test_user_context)

        assert isinstance(manager, InfisicalSecretManager)
        mock_infisical_client.assert_called_once_with(
            host="https://app.infisical.com",  # Default
            client_id="test-id",
            client_secret="test-secret",
        )

    @patch("infisical_sdk.client.InfisicalSDKClient")
    def test_create_infisical_scopes_the_secret_path_per_workspace(
        self, mock_infisical_client, mock_db_session, test_user_context
    ):
        """Two workspaces must not share a secret path.

        Names are unique per workspace, not globally, and users choose some of
        them. A shared path means one workspace reads and overwrites another's
        value under the same name.
        """
        settings = SecretManagerSettings(
            SECRET_MANAGER_TYPE="infisical",
            SECRET_MANAGER_ACCESS_KEY="test-id",
            SECRET_MANAGER_SECRET_KEY="test-secret",
            SECRET_MANAGER_PROJECT_ID="proj-1",
        )
        factory = SecretManagerFactory(settings)

        manager = factory.create(session=mock_db_session, user_context=test_user_context)

        assert test_user_context.workspace_id in manager._secret_path

    def test_create_infisical_requires_project_id(self, mock_db_session, test_user_context):
        """Without a project id there is no Infisical project to read or write."""
        settings = SecretManagerSettings(
            SECRET_MANAGER_TYPE="infisical",
            SECRET_MANAGER_ACCESS_KEY="test-id",
            SECRET_MANAGER_SECRET_KEY="test-secret",
        )

        with pytest.raises(ValueError, match="SECRET_MANAGER_PROJECT_ID"):
            SecretManagerFactory(settings)

    def test_create_infisical_missing_credentials(self, mock_db_session, test_user_context):
        """Test that Infisical requires credentials."""
        settings = SecretManagerSettings(
            SECRET_MANAGER_TYPE="infisical",
            # Missing credentials
        )
        with pytest.raises(ValueError, match="Infisical credentials not configured"):
            SecretManagerFactory(settings)

    def test_create_infisical_partial_credentials(self, mock_db_session, test_user_context):
        """Test that Infisical requires both access and secret keys."""
        settings = SecretManagerSettings(
            SECRET_MANAGER_TYPE="infisical",
            SECRET_MANAGER_ACCESS_KEY="test-key",
            # Missing SECRET_MANAGER_SECRET_KEY
        )
        with pytest.raises(ValueError, match="Infisical credentials not configured"):
            SecretManagerFactory(settings)

    def test_create_invalid_type(self, mock_db_session, test_user_context):
        """Test that invalid secret manager type raises error."""
        settings = SecretManagerSettings(SECRET_MANAGER_TYPE="invalid_type")
        factory = SecretManagerFactory(settings)

        with pytest.raises(ValueError, match="Invalid SECRET_MANAGER_TYPE"):
            factory.create(session=mock_db_session, user_context=test_user_context)

    def test_create_case_insensitive(self, mock_db_session, test_user_context):
        """Test that secret manager type is case-insensitive."""
        settings = SecretManagerSettings(SECRET_MANAGER_TYPE="DATABASE")
        factory = SecretManagerFactory(settings)

        manager = factory.create(session=mock_db_session, user_context=test_user_context)

        assert isinstance(manager, DatabaseSecretManager)

    # Dropped: test_create_infisical_sdk_not_installed. infisicalsdk is a hard
    # dependency of agentarea-secrets, so the import cannot fail and the branch
    # that reported it no longer exists.

    def test_factory_reusable_for_multiple_contexts(self, mock_db_session, test_user_context, test_admin_context):
        """Test that same factory can create managers for different contexts."""
        settings = SecretManagerSettings(SECRET_MANAGER_TYPE="database")
        factory = SecretManagerFactory(settings)

        # Create manager for regular user
        manager1 = factory.create(session=mock_db_session, user_context=test_user_context)
        assert manager1.workspace_id == "test-workspace-456"

        # Create manager for admin user (same factory, different context)
        manager2 = factory.create(session=mock_db_session, user_context=test_admin_context)
        assert manager2.workspace_id == "test-workspace-456"

        # Both are DatabaseSecretManager but with different contexts
        assert isinstance(manager1, DatabaseSecretManager)
        assert isinstance(manager2, DatabaseSecretManager)
        assert manager1 is not manager2  # Different instances
