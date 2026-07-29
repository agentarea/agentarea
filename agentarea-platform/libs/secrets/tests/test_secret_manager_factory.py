"""Unit tests for secret manager factory.

Tests factory logic for creating different secret manager types.
"""

from unittest.mock import patch

import pytest
from agentarea_common.config.secrets import get_secret_manager_settings
from agentarea_secrets.database_secret_manager import DatabaseSecretManager
from agentarea_secrets.infisical_secret_manager import InfisicalSecretManager
from agentarea_secrets.secret_manager_factory import get_real_secret_manager, get_secret_manager
from cryptography.fernet import Fernet

# Valid Fernet key used wherever the "database" secret manager needs to be
# constructed. Not a real secret, just a key shape the factory accepts.
VALID_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")


@pytest.fixture(autouse=True)
def _reset_secret_manager_settings_cache():
    """get_secret_manager_settings() is @lru_cache'd, so env-var patches made
    by individual tests are invisible unless the cache is cleared around
    each test.
    """
    get_secret_manager_settings.cache_clear()
    yield
    get_secret_manager_settings.cache_clear()


class TestSecretManagerFactory:
    """Unit tests for secret manager factory functions."""

    @patch.dict("os.environ", {"SECRET_MANAGER_ENCRYPTION_KEY": VALID_ENCRYPTION_KEY})
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

    @patch.dict("os.environ", {"SECRET_MANAGER_ENCRYPTION_KEY": VALID_ENCRYPTION_KEY})
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
            "SECRET_MANAGER_TYPE": "infisical",
            "SECRET_MANAGER_ENDPOINT": "https://test.infisical.com",
            "SECRET_MANAGER_ACCESS_KEY": "test-client-id",
            "SECRET_MANAGER_SECRET_KEY": "test-client-secret",
        },
    )
    @patch("infisical_sdk.client.InfisicalSDKClient")
    def test_get_secret_manager_infisical_type(
        self, mock_infisical_client, mock_db_session, test_user_context
    ):
        """Test creating Infisical secret manager with valid credentials."""
        manager = get_secret_manager(
            secret_manager_type="infisical",
            session=mock_db_session,
            user_context=test_user_context,
        )

        assert isinstance(manager, InfisicalSecretManager)
        # Verify InfisicalSDKClient was initialized with correct params
        mock_infisical_client.assert_called_once_with(
            host="https://test.infisical.com",
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

    @patch.dict("os.environ", {"SECRET_MANAGER_TYPE": "infisical"}, clear=True)
    def test_get_secret_manager_infisical_missing_credentials(
        self, mock_db_session, test_user_context
    ):
        """Test that Infisical type raises error when credentials missing."""
        with pytest.raises(ValueError, match="Infisical credentials not configured"):
            get_secret_manager(
                secret_manager_type="infisical",
                session=mock_db_session,
                user_context=test_user_context,
            )

    @patch.dict(
        "os.environ",
        {
            "SECRET_MANAGER_TYPE": "infisical",
            "SECRET_MANAGER_ACCESS_KEY": "test-id",
            # Missing SECRET_MANAGER_SECRET_KEY
        },
        clear=True,
    )
    def test_get_secret_manager_infisical_partial_credentials(
        self, mock_db_session, test_user_context
    ):
        """Test that Infisical type raises error with partial credentials."""
        with pytest.raises(ValueError, match="Infisical credentials not configured"):
            get_secret_manager(
                secret_manager_type="infisical",
                session=mock_db_session,
                user_context=test_user_context,
            )

    @patch.dict("os.environ", {"SECRET_MANAGER_TYPE": "invalid_type"})
    def test_get_secret_manager_invalid_type(self, mock_db_session, test_user_context):
        """Test that invalid secret manager type raises error."""
        with pytest.raises(ValueError, match="Invalid SECRET_MANAGER_TYPE"):
            get_secret_manager(
                secret_manager_type="invalid_type",
                session=mock_db_session,
                user_context=test_user_context,
            )

    @patch.dict("os.environ", {"SECRET_MANAGER_TYPE": "local"})
    def test_get_secret_manager_local_type_not_supported(self, mock_db_session, test_user_context):
        """Test that 'local' type is not supported anymore."""
        with pytest.raises(ValueError, match="Invalid SECRET_MANAGER_TYPE.*local"):
            get_secret_manager(
                secret_manager_type="local",
                session=mock_db_session,
                user_context=test_user_context,
            )

    @patch.dict(
        "os.environ",
        {"SECRET_MANAGER_TYPE": "database", "SECRET_MANAGER_ENCRYPTION_KEY": VALID_ENCRYPTION_KEY},
    )
    def test_get_real_secret_manager_defaults_to_database(self, mock_db_session, test_user_context):
        """Test that get_real_secret_manager uses database by default."""
        manager = get_real_secret_manager(
            session=mock_db_session,
            user_context=test_user_context,
        )

        assert isinstance(manager, DatabaseSecretManager)

    @patch.dict(
        "os.environ", {"SECRET_MANAGER_ENCRYPTION_KEY": VALID_ENCRYPTION_KEY}, clear=True
    )
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
            "SECRET_MANAGER_ENDPOINT": "https://test.infisical.com",
            "SECRET_MANAGER_ACCESS_KEY": "test-client-id",
            "SECRET_MANAGER_SECRET_KEY": "test-client-secret",
        },
    )
    @patch("infisical_sdk.client.InfisicalSDKClient")
    def test_get_real_secret_manager_reads_env_var(
        self, mock_infisical_client, mock_db_session, test_user_context
    ):
        """Test that get_real_secret_manager reads SECRET_MANAGER_TYPE from env."""
        manager = get_real_secret_manager(
            session=mock_db_session,
            user_context=test_user_context,
        )

        assert isinstance(manager, InfisicalSecretManager)

    @patch("infisical_sdk.client.InfisicalSDKClient", side_effect=ImportError("No module"))
    @patch.dict(
        "os.environ",
        {
            "SECRET_MANAGER_TYPE": "infisical",
            "SECRET_MANAGER_ACCESS_KEY": "test-id",
            "SECRET_MANAGER_SECRET_KEY": "test-secret",
        },
    )
    def test_get_secret_manager_infisical_sdk_not_installed(
        self, mock_client, mock_db_session, test_user_context
    ):
        """Test error message when Infisical SDK is not installed."""
        with pytest.raises(ValueError, match="Infisical SDK not installed"):
            get_secret_manager(
                secret_manager_type="infisical",
                session=mock_db_session,
                user_context=test_user_context,
            )
