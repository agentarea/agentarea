"""SecretsToolset — manage workspace secrets."""

import builtins
import json
from typing import Annotated

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.authorization import assert_workspace_admin
from agentarea_secrets.catalog_service import (
    DuplicateSecretNameError,
    ManagedSecretError,
    SecretCatalogService,
    SecretInUseError,
    SecretNotFoundError,
)
from agentarea_secrets.naming import SecretNameError
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .base import platform_context


class SecretOutput(BaseModel):
    id: str = Field(description="Secret id (UUID).")
    name: str = Field(description="Secret name, the handle other resources reference it by.")
    description: str | None = Field(description="What the secret is for.")


class SecretCreated(BaseModel):
    created: bool = Field(description="True once the secret is stored.")
    id: str = Field(description="Secret id (UUID).")
    name: str = Field(description="Secret name.")


class SecretDeleted(BaseModel):
    deleted: bool = Field(description="True once the secret is gone.")
    name: str = Field(description="Name of the deleted secret.")


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

    Writing is gated on the same authority as ``POST /v1/secrets``. Without
    that, an agent is a second door onto the same store: a member who cannot
    mint a workspace credential through the API could mint one by asking an
    agent to. Listing stays open — it returns names, never values, exactly as
    the REST listing does.
    """

    open_world = False

    @tool_method(display_name="List secrets", effect="read", output=builtins.list[SecretOutput])
    @unrestricted("names only, never values, exactly as the REST listing returns them")
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

    @tool_method(display_name="Create secret", effect="privileged", output=SecretCreated)
    @enforced_in_handler("workspace admin, asserted before the catalog is touched")
    async def create(
        self,
        name: Annotated[
            str,
            Field(
                description=(
                    "Secret name, unique in the workspace: 2-64 characters of lowercase "
                    "letters, digits, `-` and `_`, starting and ending with a letter or digit."
                )
            ),
        ],
        value: Annotated[
            str, Field(description="Secret value; stored encrypted and never returned.")
        ],
        description: Annotated[str | None, Field(description="What the secret is for.")] = None,
    ) -> str:
        """Create a secret. Fails if the name is taken or reserved by the platform."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            _event_broker,
            secret_mgr,
        ):
            try:
                await assert_workspace_admin(user_ctx)
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            catalog = SecretCatalogService(session, user_ctx, secret_mgr)
            try:
                secret = await catalog.create_user_secret(name, value, description)
            except (SecretNameError, DuplicateSecretNameError) as exc:
                raise ToolError(str(exc)) from exc
            return json.dumps({"created": True, "id": str(secret.id), "name": name})

    @tool_method(
        display_name="Delete secret",
        effect="destructive",
        idempotent=True,
        output=SecretDeleted,
    )
    @enforced_in_handler("workspace admin, asserted before the catalog is touched")
    async def delete(
        self,
        name: Annotated[str, Field(description="Secret name, from `secrets_list`.")],
    ) -> str:
        """Delete one of the workspace's own secrets by name."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            _event_broker,
            secret_mgr,
        ):
            try:
                await assert_workspace_admin(user_ctx)
            except HTTPException as exc:
                raise ToolError(exc.detail) from exc
            catalog = SecretCatalogService(session, user_ctx, secret_mgr)
            try:
                secret = await catalog.get_by_name(name)
                await catalog.delete_user_secret(secret.id)
            except SecretNotFoundError:
                raise ToolError("No such secret") from None
            except ManagedSecretError as exc:
                raise ToolError(str(exc)) from exc
            except SecretInUseError as exc:
                raise ToolError(str(exc)) from exc
            return json.dumps({"deleted": True, "name": name})
