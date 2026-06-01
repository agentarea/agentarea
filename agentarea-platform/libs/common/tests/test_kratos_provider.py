"""Unit tests for Kratos authentication provider."""

import base64
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from agentarea_common.auth.providers.kratos import KratosAuthProvider


class TestKratosAuthProvider:
    """Test suite for KratosAuthProvider."""

    @pytest.fixture
    def sample_jwks(self):
        """Sample JWKS for testing."""
        return {
            "keys": [
                {
                    "kty": "EC",
                    "kid": "test-key-1",
                    "use": "sig",
                    "alg": "ES256",
                    "crv": "P-256",
                    "x": "MKBCTNIcKUSDii11ySs3526iDZ8AiTo7Tu6KPAqv7D4",
                    "y": "4Etl6SRW2YiLUrN5vfvVHuhp7x8PxltmWWlbbM4IFyM",
                    "d": "870MB6gfuTJ4HtUnUvYMyJpr5eUZNP4Bk43bVdj3eAE",
                }
            ]
        }

    @pytest.fixture
    def jwks_b64(self, sample_jwks):
        """Base64-encoded JWKS."""
        return base64.b64encode(json.dumps(sample_jwks).encode()).decode()

    @pytest.fixture
    def kratos_provider(self, jwks_b64):
        """Create Kratos provider for testing."""
        config = {
            "jwks_b64": jwks_b64,
            "issuer": "https://test.agentarea.dev",
            "audience": "test-api",
        }
        return KratosAuthProvider(config)

    def test_provider_initialization_success(self, jwks_b64):
        """Test successful provider initialization."""
        config = {
            "jwks_b64": jwks_b64,
            "issuer": "https://test.agentarea.dev",
            "audience": "test-api",
        }
        provider = KratosAuthProvider(config)

        assert provider.issuer == "https://test.agentarea.dev"
        assert provider.audience == "test-api"
        assert provider.get_provider_name() == "kratos"

    def test_provider_initialization_missing_jwks(self):
        """Test provider initialization fails without JWKS."""
        config = {
            "issuer": "https://test.agentarea.dev",
            "audience": "test-api",
        }

        with pytest.raises(ValueError, match="jwks_b64 is required"):
            KratosAuthProvider(config)

    def test_provider_initialization_invalid_jwks(self):
        """Test provider initialization fails with invalid JWKS."""
        config = {
            "jwks_b64": "invalid-base64",
            "issuer": "https://test.agentarea.dev",
            "audience": "test-api",
        }

        with pytest.raises(ValueError, match="Failed to decode JWKS"):
            KratosAuthProvider(config)

    def test_provider_initialization_default_values(self, jwks_b64):
        """Test provider uses default values when not provided."""
        config = {"jwks_b64": jwks_b64}
        provider = KratosAuthProvider(config)

        assert provider.issuer == "https://agentarea.dev"
        assert provider.audience == "agentarea-api"

    @pytest.mark.asyncio
    async def test_verify_token_missing_kid(self, kratos_provider):
        """Test token verification fails when kid is missing."""
        # Create token without kid in header
        token = jwt.encode(
            {"sub": "test-user", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "test-secret",
            algorithm="HS256",
        )

        result = await kratos_provider.verify_token(token)

        assert not result.is_authenticated
        assert "missing key id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_verify_token_key_not_found(self, kratos_provider):
        """Test token verification fails when key ID not found in JWKS."""
        # Create token with non-existent kid
        headers = {"kid": "non-existent-key"}
        token = jwt.encode(
            {"sub": "test-user", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "test-secret",
            algorithm="HS256",
            headers=headers,
        )

        result = await kratos_provider.verify_token(token)

        assert not result.is_authenticated
        assert "key not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_verify_token_expired(self, kratos_provider):
        """Test token verification fails for expired tokens."""
        # Create expired token
        headers = {"kid": "test-key-1"}
        payload = {
            "sub": "test-user",
            "iss": "https://test.agentarea.dev",
            "aud": "test-api",
            "exp": datetime.now(UTC) - timedelta(hours=1),  # Expired
            "iat": datetime.now(UTC) - timedelta(hours=2),
        }

        # This will fail signature validation before expiry check
        # so we'll just test the expired signature error handling
        token = "expired.token.here"

        with patch.object(jwt, "get_unverified_header", return_value={"kid": "test-key-1"}):
            with patch.object(
                jwt, "decode", side_effect=jwt.ExpiredSignatureError("Token expired")
            ):
                result = await kratos_provider.verify_token(token)

        assert not result.is_authenticated
        assert "expired" in result.error.lower()

    @pytest.mark.asyncio
    async def test_verify_token_invalid_signature(self, kratos_provider):
        """Test token verification fails for invalid signature."""
        headers = {"kid": "test-key-1"}
        token = jwt.encode(
            {"sub": "test-user", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "wrong-secret",
            algorithm="HS256",
            headers=headers,
        )

        result = await kratos_provider.verify_token(token)

        assert not result.is_authenticated
        assert "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_verify_token_missing_sub_claim(self, kratos_provider):
        """Test token verification fails when sub claim is missing."""
        headers = {"kid": "test-key-1"}

        with patch.object(jwt, "get_unverified_header", return_value=headers):
            with patch.object(
                jwt,
                "decode",
                return_value={
                    "iss": "https://test.agentarea.dev",
                    "aud": "test-api",
                    "exp": datetime.now(UTC).timestamp() + 3600,
                },
            ):
                with patch.object(
                    jwt.algorithms.ECAlgorithm, "from_jwk", return_value=MagicMock()
                ):
                    result = await kratos_provider.verify_token("test.token.here")

        assert not result.is_authenticated
        assert "missing user id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_verify_token_invalid_claims(self, kratos_provider):
        """Test token verification fails for invalid claims."""
        headers = {"kid": "test-key-1"}

        with patch.object(jwt, "get_unverified_header", return_value=headers):
            with patch.object(
                jwt,
                "decode",
                return_value={
                    "sub": "test-user",
                    "iss": "https://wrong-issuer.com",  # Wrong issuer
                    "aud": "test-api",
                    "exp": 0,  # Expired timestamp
                },
            ):
                with patch.object(
                    jwt.algorithms.ECAlgorithm, "from_jwk", return_value=MagicMock()
                ):
                    result = await kratos_provider.verify_token("test.token.here")

        assert not result.is_authenticated
        assert "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_verify_token_success(self, kratos_provider):
        """Test successful token verification."""
        headers = {"kid": "test-key-1"}
        payload = {
            "sub": "test-user-123",
            "email": "test@example.com",
            "iss": "https://test.agentarea.dev",
            "aud": "test-api",
            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
            "iat": datetime.now(UTC).timestamp(),
        }

        with patch.object(jwt, "get_unverified_header", return_value=headers):
            with patch.object(jwt, "decode", return_value=payload):
                with patch.object(
                    jwt.algorithms.ECAlgorithm, "from_jwk", return_value=MagicMock()
                ):
                    result = await kratos_provider.verify_token("test.token.here")

        assert result.is_authenticated
        assert result.user_id == "test-user-123"
        assert result.token is not None
        assert result.token.user_id == "test-user-123"
        assert result.token.email == "test@example.com"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_verify_token_success_without_email(self, kratos_provider):
        """Test successful token verification without email claim."""
        headers = {"kid": "test-key-1"}
        payload = {
            "sub": "test-user-456",
            "iss": "https://test.agentarea.dev",
            "aud": "test-api",
            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
            "iat": datetime.now(UTC).timestamp(),
        }

        with patch.object(jwt, "get_unverified_header", return_value=headers):
            with patch.object(jwt, "decode", return_value=payload):
                with patch.object(
                    jwt.algorithms.ECAlgorithm, "from_jwk", return_value=MagicMock()
                ):
                    result = await kratos_provider.verify_token("test.token.here")

        assert result.is_authenticated
        assert result.user_id == "test-user-456"
        assert result.token.email is None

    @pytest.mark.asyncio
    async def test_get_user_info(self, kratos_provider):
        """Test get_user_info returns basic user info."""
        user_info = await kratos_provider.get_user_info("test-user-123")

        assert user_info is not None
        assert user_info["user_id"] == "test-user-123"
        assert user_info["provider"] == "kratos"

    def test_get_provider_name(self, kratos_provider):
        """Test get_provider_name returns 'kratos'."""
        assert kratos_provider.get_provider_name() == "kratos"

    @pytest.mark.asyncio
    async def test_verify_token_unexpected_error(self, kratos_provider):
        """Test token verification handles unexpected errors gracefully."""
        with patch.object(jwt, "get_unverified_header", side_effect=Exception("Unexpected error")):
            result = await kratos_provider.verify_token("test.token.here")

        assert not result.is_authenticated
        assert "error verifying token" in result.error.lower()
