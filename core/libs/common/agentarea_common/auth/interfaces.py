"""
Authentication provider interfaces for AgentArea.

This module defines the base interface for authentication providers
and common data structures used across the authentication system.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class AuthToken:
    """Represents a verified authentication token."""
    user_id: str
    email: Optional[str] = None
    claims: Optional[Dict[str, Any]] = None
    expires_at: Optional[int] = None


@dataclass
class AuthResult:
    """Represents the result of an authentication operation."""
    is_authenticated: bool
    user_id: Optional[str] = None
    token: Optional[AuthToken] = None
    error: Optional[str] = None


class AuthProviderInterface(ABC):
    """Base interface for authentication providers."""

    @abstractmethod
    async def verify_token(self, token: str) -> AuthResult:
        """
        Verify an authentication token.
        
        Args:
            token: The token to verify
            
        Returns:
            AuthResult containing the verification result
        """
        pass

    @abstractmethod
    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user information by user ID.
        
        Args:
            user_id: The user ID to look up
            
        Returns:
            Dictionary containing user information or None if not found
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Get the name of this authentication provider.
        
        Returns:
            The provider name
        """
        pass
