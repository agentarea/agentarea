"""Authentication provider interfaces for AgentArea.

This module defines the base interface for authentication providers
and common data structures used across the authentication system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AuthToken:
    """Represents a verified authentication token."""

    user_id: str
    email: str | None = None
    claims: dict[str, Any] | None = None
    expires_at: int | None = None


@dataclass
class AuthResult:
    """Represents the result of an authentication operation."""

    is_authenticated: bool
    user_id: str | None = None
    token: AuthToken | None = None
    error: str | None = None


class AuthProviderInterface(ABC):
    """Base interface for authentication providers."""

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
