"""Simple JWT authentication provider for AgentArea.

This module provides a simple JWT validation implementation
that validates Clerk's JWT tokens.
"""

import logging
import os
from typing import Any

import jwt

from ..interfaces import AuthResult, AuthToken
from .base import BaseAuthProvider

logger = logging.getLogger(__name__)


class SimpleJWTProvider(BaseAuthProvider):
    """Simple JWT authentication provider implementation for validating Clerk tokens."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the simple JWT auth provider.

        Args:
            config: Configuration dictionary for the provider
                   Should include:
                   - secret_key: Secret key for JWT validation (Clerk's secret key)
                   - algorithm: JWT algorithm (default: HS256)
                   - issuer: Expected issuer (Clerk's issuer)
                   - audience: Expected audience (optional)
        """
        super().__init__(config)
        # For Clerk, we use their secret key for validation
        self.secret_key = self.config.get("secret_key") or os.getenv(
            "CLERK_SECRET_KEY", "your-secret-key-change-in-production"
        )
        self.algorithm = self.config.get("algorithm", "HS256")
        self.issuer = self.config.get("issuer") or os.getenv("CLERK_ISSUER")
        self.audience = self.config.get("audience") or os.getenv("CLERK_AUDIENCE")

    async def verify_token(self, token: str) -> AuthResult:
        """Verify a Clerk JWT token.

        Args:
            token: The JWT token to verify

        Returns:
            AuthResult containing the verification result
        """
        try:
            # Decode and verify the token using Clerk's secret
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                audience=self.audience,
                issuer=self.issuer,
            )

            # Validate claims
            if not self._validate_claims(payload, self.issuer):
                return AuthResult(is_authenticated=False, error="Invalid token claims")

            # Extract user information from Clerk's token structure
            user_id = payload.get("sub") or payload.get("user_id")
            if not user_id:
                return AuthResult(is_authenticated=False, error="Token missing user ID")

            # Clerk stores email in different possible fields
            email = payload.get("email") or payload.get("email_address")

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

        For Clerk tokens, we return basic user info from the token claims.
        In a real implementation, this would query a user database.

        Args:
            user_id: The user ID to look up

        Returns:
            Dictionary containing user information or None if not found
        """
        # In a real implementation, this would query a user database
        # For now, we return basic user info
        return {"user_id": user_id, "provider": "clerk"}

    def get_provider_name(self) -> str:
        """Get the name of this authentication provider.

        Returns:
            The provider name
        """
        return "clerk"
