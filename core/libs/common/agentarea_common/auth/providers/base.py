"""Base authentication provider for AgentArea.

This module provides a base implementation for authentication providers
that can be extended by specific provider implementations.
"""

import logging
from abc import abstractmethod
from typing import Any

import httpx

from ..interfaces import AuthProviderInterface, AuthResult

logger = logging.getLogger(__name__)


class BaseAuthProvider(AuthProviderInterface):
    """Base authentication provider implementation."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the base auth provider.

        Args:
            config: Configuration dictionary for the provider
        """
        self.config = config or {}
        self._jwks_cache = None
        self._jwks_cache_time = 0
        self._jwks_cache_ttl = 3600  # 1 hour cache TTL

    @abstractmethod
    async def verify_token(self, token: str) -> AuthResult:
        """Verify an authentication token.

        Args:
            token: The token to verify

        Returns:
            AuthResult containing the verification result
        """
        pass

    @abstractmethod
    async def get_user_info(self, user_id: str) -> dict[str, Any] | None:
        """Get user information by user ID.

        Args:
            user_id: The user ID to look up

        Returns:
            Dictionary containing user information or None if not found
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the name of this authentication provider.

        Returns:
            The provider name
        """
        pass

    async def _fetch_jwks(self, jwks_url: str) -> dict[str, Any]:
        """Fetch JWKS (JSON Web Key Set) from the provider.

        Args:
            jwks_url: URL to fetch JWKS from

        Returns:
            Dictionary containing the JWKS
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(jwks_url)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch JWKS from {jwks_url}: {e}")
            raise

    def _find_key_by_kid(self, jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
        """Find a key in JWKS by key ID.

        Args:
            jwks: The JWKS dictionary
            kid: The key ID to find

        Returns:
            The key dictionary or None if not found
        """
        keys = jwks.get("keys", [])
        for key in keys:
            if key.get("kid") == kid:
                return key
        return None

    def _validate_claims(self, payload: dict[str, Any], issuer: str | None = None) -> bool:
        """Validate JWT claims.

        Args:
            payload: The JWT payload
            issuer: Expected issuer (optional)

        Returns:
            True if claims are valid, False otherwise
        """
        import time

        # Check expiration
        exp = payload.get("exp")
        if exp and exp < time.time():
            logger.warning("Token has expired")
            return False

        # Check not before
        nbf = payload.get("nbf")
        if nbf and nbf > time.time():
            logger.warning("Token not yet valid")
            return False

        # Check issuer if provided
        if issuer and payload.get("iss") != issuer:
            logger.warning("Token issuer mismatch")
            return False

        return True
