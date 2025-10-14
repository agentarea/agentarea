"""Authentication provider factory for AgentArea.

This module provides a factory pattern implementation for creating
authentication providers based on configuration.
"""

from typing import Any

from ..interfaces import AuthProviderInterface
from .kratos import KratosAuthProvider


class AuthProviderFactory:
    """Factory for creating authentication providers."""

    @staticmethod
    def create_provider(
        provider_name: str, config: dict[str, Any] | None = None
    ) -> AuthProviderInterface:
        """Create an authentication provider based on the provider name.

        Args:
            provider_name: Name of the provider to create
            config: Configuration dictionary for the provider

        Returns:
            AuthProviderInterface instance

        Raises:
            ValueError: If the provider name is not supported
        """
        config = config or {}

        if provider_name.lower() == "kratos":
            # Config should contain: jwks_b64, issuer, audience
            # These are now provided from AuthSettings, not os.getenv
            if not all(k in config for k in ["jwks_b64", "issuer", "audience"]):
                raise ValueError(
                    "Kratos provider requires 'jwks_b64', 'issuer', and 'audience' in config"
                )

            return KratosAuthProvider(config)

        # Add other providers here as needed
        # elif provider_name.lower() == "auth0":
        #     return Auth0AuthProvider(config)
        # elif provider_name.lower() == "firebase":
        #     return FirebaseAuthProvider(config)

        raise ValueError(f"Unsupported authentication provider: {provider_name}")

    @staticmethod
    def create_provider_from_settings() -> AuthProviderInterface:
        """Create an authentication provider based on application settings.

        Returns:
            AuthProviderInterface instance
        """
        from agentarea_common.config.app import get_app_settings

        settings = get_app_settings()

        # Currently only Kratos is supported
        return AuthProviderFactory.create_provider(
            "kratos",
            config={
                "jwks_b64": settings.KRATOS_JWKS_B64,
                "issuer": settings.KRATOS_ISSUER,
                "audience": settings.KRATOS_AUDIENCE,
            },
        )
