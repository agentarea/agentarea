"""
Authentication provider factory for AgentArea.

This module provides a factory pattern implementation for creating
authentication providers based on configuration.
"""

from typing import Dict, Any, Optional
import os

from ..interfaces import AuthProviderInterface
from .clerk import ClerkAuthProvider


class AuthProviderFactory:
    """Factory for creating authentication providers."""

    @staticmethod
    def create_provider(provider_name: str, config: Optional[Dict[str, Any]] = None) -> AuthProviderInterface:
        """
        Create an authentication provider based on the provider name.
        
        Args:
            provider_name: Name of the provider to create
            config: Configuration dictionary for the provider
            
        Returns:
            AuthProviderInterface instance
            
        Raises:
            ValueError: If the provider name is not supported
        """
        config = config or {}
        
        if provider_name.lower() == "clerk":
            # Get Clerk configuration from environment or config
            clerk_config = {
                "jwks_url": config.get("jwks_url") or os.getenv("CLERK_JWKS_URL"),
                "issuer": config.get("issuer") or os.getenv("CLERK_ISSUER"),
                "audience": config.get("audience") or os.getenv("CLERK_AUDIENCE"),
            }
            
            # Remove None values
            clerk_config = {k: v for k, v in clerk_config.items() if v is not None}
            
            return ClerkAuthProvider(clerk_config)
        
        # Add other providers here as needed
        # elif provider_name.lower() == "auth0":
        #     return Auth0AuthProvider(config)
        # elif provider_name.lower() == "firebase":
        #     return FirebaseAuthProvider(config)
        
        raise ValueError(f"Unsupported authentication provider: {provider_name}")

    @staticmethod
    def create_provider_from_env() -> AuthProviderInterface:
        """
        Create an authentication provider based on environment variables.
        
        Returns:
            AuthProviderInterface instance
        """
        provider_name = os.getenv("AUTH_PROVIDER", "clerk")
        return AuthProviderFactory.create_provider(provider_name)
