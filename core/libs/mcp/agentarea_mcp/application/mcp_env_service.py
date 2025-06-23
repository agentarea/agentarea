"""MCP Environment Variables Service.

Handles environment variables for MCP server instances using the secret manager.
Instance configs only store references to secrets, never actual values.
"""

from uuid import UUID

from agentarea_common.infrastructure.secret_manager import BaseSecretManager


class MCPEnvironmentService:
    """Service for managing MCP server instance environment variables.

    Security principle: Instance configs never store actual values,
    only references to secrets stored in the secret manager.
    """

    def __init__(self, secret_manager: BaseSecretManager):
        self.secret_manager = secret_manager

    def _get_secret_key(self, instance_id: UUID, env_name: str) -> str:
        """Generate predictable secret key for environment variable."""
        return f"mcp_instance_{instance_id}_{env_name}"

    async def set_instance_environment(
        self, instance_id: UUID, env_vars: dict[str, str]
    ) -> list[str]:
        """Store environment variables for an MCP instance using the secret manager.

        Args:
            instance_id: The MCP server instance ID
            env_vars: Dictionary of environment variable names and values

        Returns:
            List of environment variable names that were stored
        """
        stored_env_names: list[str] = []

        for env_name, env_value in env_vars.items():
            secret_key = self._get_secret_key(instance_id, env_name)
            await self.secret_manager.set_secret(secret_key, env_value)
            stored_env_names.append(env_name)

        return stored_env_names

    async def get_instance_environment(
        self, instance_id: UUID, env_names: list[str]
    ) -> dict[str, str]:
        """Retrieve environment variables for an MCP instance from the secret manager.

        Args:
            instance_id: The MCP server instance ID
            env_names: List of environment variable names to retrieve

        Returns:
            Dictionary of environment variable names and values
        """
        env_vars: dict[str, str] = {}

        for env_name in env_names:
            secret_key = self._get_secret_key(instance_id, env_name)
            secret_value = await self.secret_manager.get_secret(secret_key)
            if secret_value is not None:
                env_vars[env_name] = secret_value

        return env_vars

    async def update_instance_environment(
        self, instance_id: UUID, env_updates: dict[str, str]
    ) -> list[str]:
        """Update specific environment variables for an MCP instance.

        Args:
            instance_id: The MCP server instance ID
            env_updates: Dictionary of environment variable names and new values

        Returns:
            List of environment variable names that were updated
        """
        return await self.set_instance_environment(instance_id, env_updates)

    async def delete_instance_environment(
        self, instance_id: UUID, env_names: list[str]
    ) -> list[str]:
        """Delete environment variables for an MCP instance.

        Args:
            instance_id: The MCP server instance ID
            env_names: List of environment variable names to delete

        Returns:
            List of environment variable names that were deleted
        """
        deleted_env_names: list[str] = []

        for env_name in env_names:
            secret_key = self._get_secret_key(instance_id, env_name)
            # Set to empty string to "delete" (since BaseSecretManager has no delete method)
            await self.secret_manager.set_secret(secret_key, "")
            deleted_env_names.append(env_name)

        return deleted_env_names

    async def get_configured_env_names(
        self, instance_id: UUID, expected_env_names: list[str]
    ) -> list[str]:
        """Get list of environment variables that are actually configured for an instance.

        Args:
            instance_id: The MCP server instance ID
            expected_env_names: List of expected environment variable names

        Returns:
            List of environment variable names that have values in secret manager
        """
        configured_env_names: list[str] = []

        for env_name in expected_env_names:
            secret_key = self._get_secret_key(instance_id, env_name)
            secret_value = await self.secret_manager.get_secret(secret_key)
            if secret_value is not None and secret_value != "":
                configured_env_names.append(env_name)

        return configured_env_names
