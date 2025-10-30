"""Kratos authentication provider for AgentArea.

This module provides implementation for Ory Kratos authentication verification
using JWT tokens signed with ES256.
"""

import base64
import json
import logging
from typing import Any

import jwt

from ..interfaces import AuthResult, AuthToken
from .base import BaseAuthProvider

logger = logging.getLogger(__name__)


class KratosAuthProvider(BaseAuthProvider):
    """Kratos authentication provider implementation."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the Kratos auth provider.

        Args:
            config: Configuration dictionary for the provider
                   Should include:
                   - jwks_b64: Base64-encoded JWKS from Kratos config
                   - issuer: Expected issuer URL (default: https://agentarea.dev)
                   - audience: Expected audience (default: agentarea-api)
        """
        super().__init__(config)
        self.jwks_b64 = self.config.get("jwks_b64")
        self.issuer = self.config.get("issuer", "https://agentarea.dev")
        self.audience = self.config.get("audience", "agentarea-api")

        if not self.jwks_b64:
            raise ValueError("jwks_b64 is required for KratosAuthProvider")

        # Decode and parse JWKS
        try:
            jwks_json = base64.b64decode(self.jwks_b64).decode("utf-8")
            self._jwks = json.loads(jwks_json)
        except Exception as e:
            raise ValueError(f"Failed to decode JWKS: {e}") from e

    async def verify_token(self, token: str) -> AuthResult:
        """Verify a Kratos JWT token.

        Args:
            token: The JWT token to verify

        Returns:
            AuthResult containing the verification result
        """
        try:
            # Decode the token header to get the key ID
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")

            if not kid:
                return AuthResult(is_authenticated=False, error="Token header missing key ID")

            # Find the key by key ID
            key = self._find_key_by_kid(self._jwks, kid)
            if not key:
                return AuthResult(is_authenticated=False, error="Key not found in JWKS")

            # Convert JWK to EC key (Kratos uses ES256)
            ec_key = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(key))

            # Verify and decode the token
            payload = jwt.decode(
                token, ec_key, algorithms=["ES256"], audience=self.audience, issuer=self.issuer
            )

            # Validate claims
            if not self._validate_claims(payload, self.issuer):
                return AuthResult(is_authenticated=False, error="Invalid token claims")

            # Extract user information
            user_id = payload.get("sub")
            if not user_id:
                return AuthResult(is_authenticated=False, error="Token missing user ID")

            email = payload.get("email")

            auth_token = AuthToken(
                user_id=user_id, email=email, claims=payload, expires_at=payload.get("exp")
            )

            return AuthResult(is_authenticated=True, user_id=user_id, token=auth_token)

        except jwt.ExpiredSignatureError:
            return AuthResult(is_authenticated=False, error="Token has expired")
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid token: {e}")
            return AuthResult(is_authenticated=False, error=f"Invalid token: {e!s}")
        except Exception as e:
            logger.error(f"Error verifying token: {e}")
            return AuthResult(is_authenticated=False, error=f"Error verifying token: {e!s}")

    async def get_user_info(self, user_id: str) -> dict[str, Any] | None:
        """Get user information by user ID.

        For Kratos, we don't fetch user info directly in this implementation
        as the token already contains the necessary information.
        In a full implementation, this would call the Kratos Admin API.

        Args:
            user_id: The user ID to look up

        Returns:
            Dictionary containing user information or None if not found
        """
        # In a real implementation, this would call the Kratos Admin API
        # For now, we return minimal user info
        return {"user_id": user_id, "provider": "kratos"}

    def get_provider_name(self) -> str:
        """Get the name of this authentication provider.

        Returns:
            The provider name
        """
        return "kratos"
