"""SecretsToolset — manage workspace secrets."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_secrets.catalog_service import (
    DuplicateSecretNameError,
    ManagedSecretError,
    SecretCatalogService,
    SecretInUseError,
    SecretNotFoundError,
)
from agentarea_secrets.naming import SecretNameError

from .base import platform_context


@toolset(
    namespace="agentarea/secrets",
    display_name="Secrets",
    description="Manage workspace secrets (names only, values are encrypted).",
    category="platform",
    plane="build",
)
class SecretsToolset(Toolset):
    """Manage the workspace's own secrets: list, create, delete.

    Everything here goes through the catalog rather than the raw secret store,
    which confines it to secrets a user owns. Reaching the store directly would
    let an agent name a secret after a connection and overwrite that
    connection's live credentials — `(workspace_id, secret_name)` is unique, so
    a colliding write is an update.
    """

    @tool_method(effect="read")
    async def list(self) -> str:
        """List the workspace's own secret names. Values are not returned."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            _event_broker,
            secret_mgr,
        ):
            catalog = SecretCatalogService(session, user_ctx, secret_mgr)
            secrets = await catalog.list_user_secrets()
            return json.dumps(
                [
                    {
                        "id": str(secret.id),
                        "name": secret.secret_name,
                        "description": secret.description,
                    }
                    for secret in secrets
                ],
                default=str,
            )

    @tool_method(effect="privileged")
    async def create(self, name: str, value: str, description: str | None = None) -> str:
        """Create a secret. Fails if the name is taken or reserved by the platform."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            _event_broker,
            secret_mgr,
        ):
            catalog = SecretCatalogService(session, user_ctx, secret_mgr)
            try:
                secret = await catalog.create_user_secret(name, value, description)
            except (SecretNameError, DuplicateSecretNameError) as exc:
                return json.dumps({"created": False, "name": name, "error": str(exc)})
            return json.dumps({"created": True, "id": str(secret.id), "name": name})

    @tool_method(effect="destructive")
    async def delete(self, name: str) -> str:
        """Delete one of the workspace's own secrets by name."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            _event_broker,
            secret_mgr,
        ):
            catalog = SecretCatalogService(session, user_ctx, secret_mgr)
            try:
                secret = await catalog.get_by_name(name)
                await catalog.delete_user_secret(secret.id)
            except SecretNotFoundError:
                return json.dumps({"deleted": False, "name": name, "error": "No such secret"})
            except ManagedSecretError as exc:
                return json.dumps({"deleted": False, "name": name, "error": str(exc)})
            except SecretInUseError as exc:
                return json.dumps({"deleted": False, "name": name, "error": str(exc)})
            return json.dumps({"deleted": True, "name": name})
