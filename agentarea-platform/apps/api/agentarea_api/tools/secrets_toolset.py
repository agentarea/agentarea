"""SecretsToolset — manage workspace secrets."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset

from .base import platform_context


@toolset(
    namespace="agentarea/secrets",
    display_name="Secrets",
    description="Manage workspace secrets (names only, values are encrypted).",
    category="platform",
)
class SecretsToolset(Toolset):
    """Manage workspace secrets: list, create, delete."""

    @tool_method
    async def list(self) -> str:
        """List all secret names in the workspace (values are not returned)."""
        async with platform_context() as (
            _session,
            _user_ctx,
            _repo_factory,
            _event_broker,
            secret_mgr,
        ):
            secrets = await secret_mgr.list_secrets()
            return json.dumps(
                [
                    {
                        "name": getattr(secret, "name", str(secret)),
                        "id": str(getattr(secret, "id", secret)),
                    }
                    for secret in secrets
                ],
                default=str,
            )

    @tool_method
    async def create(self, name: str, value: str) -> str:
        """Create or update a secret."""
        async with platform_context() as (
            _session,
            _user_ctx,
            _repo_factory,
            _event_broker,
            secret_mgr,
        ):
            await secret_mgr.set_secret(name, value)
            return json.dumps({"created": True, "name": name})

    @tool_method
    async def delete(self, name: str) -> str:
        """Delete a secret by name."""
        async with platform_context() as (
            _session,
            _user_ctx,
            _repo_factory,
            _event_broker,
            secret_mgr,
        ):
            await secret_mgr.delete_secret(name)
            return json.dumps({"deleted": True, "name": name})
