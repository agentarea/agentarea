"""Unit tests for secret manager factory.

Tests factory logic for creating different secret manager types.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from agentarea_secrets.secret_manager_factory import get_real_secret_manager, get_secret_manager
from agentarea_secrets.database_secret_manager import DatabaseSecretManager
from agentarea_secrets.infisical_secret_manager import InfisicalSecretManager


class TestSecretManagerFactory:
    """Unit tests for secret manager factory functions."""

    def test_get_secret_manager_database_type(self, mock_db_session, test_user_context):
        """Test creating database secret manager."""
        manager = get_secret_manager(
            secret_manager_type="database",
            session=mock_db_session,
            user_context=test_user_context,
        )

        assert isinstance(manager, DatabaseSecretManager)
        assert manager.session == mock_db_session
        assert manager.workspace_id == "test-workspace-456"

    def test_get_secret_manager_database_case_insensitive(self, mock_db_session, test_user_context):
        """Test that secret manager type is case-insensitive."""
        manager = get_secret_manager(
            secret_manager_type="DATABASE",
            session=mock_db_session,
            user_context=test_user_context,
        )

        assert isinstance(manager, DatabaseSecretManager)

    def test_get_secret_manager_database_missing_session(self, test_user_context):
        """Test that database type requires session parameter."""
        with pytest.raises(ValueError, match="requires both 'session' and 'user_context'"):
            get_secret_manager(
                secret_manager_type="database",
                session=None,
                user_context=test_user_context,
            )

    def test_get_secret_manager_database_missing_user_context(self, mock_db_session):
        """Test that database type requires user_context parameter."""
        with pytest.raises(ValueError, match="requires both 'session' and 'user_context'"):
            get_secret_manager(
                secret_manager_type="database",
                session=mock_db_session,
                user_context=None,
            )

    @patch.dict(
        "os.environ",
        {
            "INFISICAL_URL": "https://test.infisical.com",
            "INFISICAL_CLIENT_ID": "test-client-id",
            "INFISICAL_CLIENT_SECRET": "test-client-secret",
            "INFISICAL_PROJECT_ID": "test-project",
            "INFISICAL_ENVIRONMENT": "test",
        },
    )
    @patch("infisical_sdk.client.InfisicalSDKClient")
    def test_get_secret_manager_infisical_type(self, mock_infisical_client):
        """Test creating Infisical secret manager with valid credentials."""
        manager = get_secret_manager(secret_manager_type="infisical")

        assert isinstance(manager, InfisicalSecretManager)
        # Verify InfisicalSDKClient was initialized with correct params
        mock_infisical_client.assert_called_once_with(
            host="https://test.infisical.com",
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

    @patch.dict("os.environ", {}, clear=True)
    def test_get_secret_manager_infisical_missing_credentials(self):
        """Test that Infisical type raises error when credentials missing."""
        with pytest.raises(ValueError, match="Infisical credentials not configured"):
            get_secret_manager(secret_manager_type="infisical")

    @patch.dict(
        "os.environ",
        {
            "INFISICAL_CLIENT_ID": "test-id",
            # Missing INFISICAL_CLIENT_SECRET
        },
    )
    def test_get_secret_manager_infisical_partial_credentials(self):
        """Test that Infisical type raises error with partial credentials."""
        with pytest.raises(ValueError, match="Infisical credentials not configured"):
            get_secret_manager(secret_manager_type="infisical")

    def test_get_secret_manager_invalid_type(self, mock_db_session, test_user_context):
        """Test that invalid secret manager type raises error."""
        with pytest.raises(ValueError, match="Invalid SECRET_MANAGER_TYPE"):
            get_secret_manager(
                secret_manager_type="invalid_type",
                session=mock_db_session,
                user_context=test_user_context,
            )

    def test_get_secret_manager_local_type_not_supported(self, mock_db_session, test_user_context):
        """Test that 'local' type is not supported anymore."""
        with pytest.raises(ValueError, match="Invalid SECRET_MANAGER_TYPE.*local"):
            get_secret_manager(
                secret_manager_type="local",
                session=mock_db_session,
                user_context=test_user_context,
            )

    @patch.dict("os.environ", {"SECRET_MANAGER_TYPE": "database"})
    def test_get_real_secret_manager_defaults_to_database(self, mock_db_session, test_user_context):
        """Test that get_real_secret_manager uses database by default."""
        manager = get_real_secret_manager(
            session=mock_db_session,
            user_context=test_user_context,
        )

        assert isinstance(manager, DatabaseSecretManager)

    @patch.dict("os.environ", {}, clear=True)
    def test_get_real_secret_manager_no_env_defaults_to_database(
        self, mock_db_session, test_user_context
    ):
        """Test that get_real_secret_manager defaults to database when no env var."""
        manager = get_real_secret_manager(
            session=mock_db_session,
            user_context=test_user_context,
        )

        assert isinstance(manager, DatabaseSecretManager)

    @patch.dict(
        "os.environ",
        {
            "SECRET_MANAGER_TYPE": "infisical",
            "INFISICAL_URL": "https://test.infisical.com",
            "INFISICAL_CLIENT_ID": "test-client-id",
            "INFISICAL_CLIENT_SECRET": "test-client-secret",
        },
    )
    @patch("infisical_sdk.client.InfisicalSDKClient")
    def test_get_real_secret_manager_reads_env_var(self, mock_infisical_client):
        """Test that get_real_secret_manager reads SECRET_MANAGER_TYPE from env."""
        manager = get_real_secret_manager()

        assert isinstance(manager, InfisicalSecretManager)

    @patch("infisical_sdk.client.InfisicalSDKClient", side_effect=ImportError("No module"))
    @patch.dict(
        "os.environ",
        {
            "INFISICAL_CLIENT_ID": "test-id",
            "INFISICAL_CLIENT_SECRET": "test-secret",
        },
    )
    def test_get_secret_manager_infisical_sdk_not_installed(self, mock_client):
        """Test error message when Infisical SDK is not installed."""
        with pytest.raises(ValueError, match="Infisical SDK not installed"):
            get_secret_manager(secret_manager_type="infisical")
