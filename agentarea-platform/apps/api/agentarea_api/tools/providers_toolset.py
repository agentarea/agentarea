"""ProvidersToolset — manage LLM provider configurations.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth is the Pydantic DTO ``ProviderConfigCreate`` /
``ProviderConfigUpdate`` in ``agentarea_llm.schemas.dto``. The contract
test in ``tests/unit/test_mcp_rest_parity.py`` enforces parity.
"""

import json
from typing import Annotated
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import requires_workspace_admin, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_llm.schemas.dto import ProviderConfigCreate, ProviderConfigUpdate
from pydantic import BaseModel, Field

from .base import platform_context


def _build_service(session, user_ctx, event_broker, secret_mgr):
    """Construct a fully-wired ProviderService for a request scope."""
    from agentarea_llm.application.provider_service import ProviderService
    from agentarea_llm.infrastructure.model_instance_repository import (
        ModelInstanceRepository,
    )
    from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
    from agentarea_llm.infrastructure.provider_config_repository import (
        ProviderConfigRepository,
    )
    from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

    return ProviderService(
        provider_spec_repo=ProviderSpecRepository(session, user_ctx),
        provider_config_repo=ProviderConfigRepository(session, user_ctx),
        model_spec_repo=ModelSpecRepository(session, user_ctx),
        model_instance_repo=ModelInstanceRepository(session, user_ctx),
        event_broker=event_broker,
        secret_manager=secret_mgr,
    )


_CONFIG_ID = "Provider configuration id (UUID), from `providers_list_configs`."


class ProviderSpecOutput(BaseModel):
    id: str = Field(description="Provider spec id (UUID); pass as provider_spec_id.")
    name: str = Field(description="Provider name, e.g. OpenAI.")
    key: str = Field(description="Stable provider key, e.g. openai.")


class ProviderConfigSummaryOutput(BaseModel):
    id: str = Field(description="Provider configuration id (UUID).")
    name: str = Field(description="Label of the configuration.")
    provider_spec_id: str = Field(description="Id of the provider spec it targets.")
    is_active: bool = Field(description="Whether models can be called through it.")


class ProviderConfigRefOutput(BaseModel):
    id: str = Field(description="Provider configuration id (UUID).")
    name: str = Field(description="Label of the configuration.")


class ProviderConfigDeletedOutput(BaseModel):
    deleted: bool = Field(description="False when no such configuration existed.")


@toolset(
    namespace="agentarea/providers",
    display_name="LLM Providers",
    description="Manage LLM provider specs and configurations.",
    category="platform",
    plane="build",
)
class ProvidersToolset(Toolset):
    """Manage LLM providers: list specs, list/create/update/delete configurations."""

    open_world = False

    @tool_method(
        display_name="List LLM provider specs", effect="read", output=list[ProviderSpecOutput]
    )
    @unrestricted("the provider catalog is platform data every member reads")
    async def list_specs(self) -> str:
        """List available LLM provider specifications (e.g. OpenAI, Anthropic)."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            service = _build_service(session, user_ctx, event_broker, secret_mgr)
            specs = await service.list_provider_specs()
            return json.dumps(
                [{"id": str(s.id), "name": s.name, "key": s.provider_key} for s in specs],
                default=str,
            )

    @tool_method(
        display_name="List LLM provider configs",
        effect="read",
        output=list[ProviderConfigSummaryOutput],
    )
    @unrestricted("configurations carry no key material and members need them to pick a model")
    async def list_configs(self) -> str:
        """List configured LLM provider connections."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            service = _build_service(session, user_ctx, event_broker, secret_mgr)
            configs = await service.list_provider_configs()
            return json.dumps(
                [
                    {
                        "id": str(c.id),
                        "name": c.name,
                        "provider_spec_id": str(c.provider_spec_id),
                        "is_active": c.is_active,
                    }
                    for c in configs
                ],
                default=str,
            )

    @tool_method(
        display_name="Create LLM provider config",
        effect="privileged",
        output=ProviderConfigRefOutput,
    )
    @requires_workspace_admin()
    async def create_config(
        self,
        provider_spec_id: Annotated[
            str, Field(description="Provider spec id (UUID), from `providers_list_specs`.")
        ],
        name: Annotated[str, Field(description="Label for the configuration, 1-255 characters.")],
        api_key: Annotated[
            str,
            Field(
                description="API key for the provider; stored encrypted and never returned. "
                "Empty for a proxy that takes keyless traffic."
            ),
        ],
        endpoint_url: Annotated[
            str,
            Field(
                description="Custom base URL for a self-hosted or proxied provider; "
                "empty for the provider's default."
            ),
        ] = "",
        description: Annotated[
            str, Field(description="What the configuration is for, at most 1000 characters.")
        ] = "",
        is_public: Annotated[
            bool,
            Field(
                description="True makes it visible to every workspace member; "
                "otherwise only to its creator."
            ),
        ] = False,
    ) -> str:
        """Create a new LLM provider configuration with API key."""
        payload = ProviderConfigCreate(
            provider_spec_id=UUID(provider_spec_id),
            name=name,
            api_key=api_key,
            endpoint_url=endpoint_url or None,
            description=description or None,
            is_public=is_public,
        )

        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            service = _build_service(session, user_ctx, event_broker, secret_mgr)
            config = await service.create_provider_config(
                payload=payload,
                created_by=user_ctx.user_id,
            )
            return json.dumps({"id": str(config.id), "name": config.name}, default=str)

    @tool_method(
        display_name="Update LLM provider config",
        effect="privileged",
        idempotent=True,
        output=ProviderConfigRefOutput,
    )
    @requires_workspace_admin()
    async def update_config(
        self,
        config_id: Annotated[str, Field(description=_CONFIG_ID)],
        name: Annotated[
            str | None, Field(description="New label; omit to keep the current one.")
        ] = None,
        api_key: Annotated[
            str | None,
            Field(
                description="New API key, replacing the stored one; empty string clears it "
                "for a keyless endpoint; omit to keep it."
            ),
        ] = None,
        endpoint_url: Annotated[
            str | None,
            Field(description="New base URL; empty string clears it; omit to keep it."),
        ] = None,
        description: Annotated[
            str | None, Field(description="New description; omit to keep the current one.")
        ] = None,
        is_active: Annotated[
            bool | None,
            Field(description="Activate (true) or deactivate (false); omit to keep it."),
        ] = None,
        is_public: Annotated[
            bool | None,
            Field(
                description="Visible to every member (true) or only its creator (false); "
                "omit to keep it."
            ),
        ] = None,
    ) -> str:
        """Update an existing LLM provider configuration. Unset kwargs leave fields unchanged."""
        patch: dict[str, object] = {}
        if name is not None:
            patch["name"] = name
        if api_key is not None:
            patch["api_key"] = api_key
        if endpoint_url is not None:
            patch["endpoint_url"] = endpoint_url
        if description is not None:
            patch["description"] = description
        if is_active is not None:
            patch["is_active"] = is_active
        if is_public is not None:
            patch["is_public"] = is_public
        payload = ProviderConfigUpdate.model_validate(patch)

        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            service = _build_service(session, user_ctx, event_broker, secret_mgr)
            config = await service.update_provider_config(
                config_id=UUID(config_id),
                payload=payload,
            )
            if not config:
                raise ToolError("Provider configuration not found")
            return json.dumps({"id": str(config.id), "name": config.name}, default=str)

    @tool_method(
        display_name="Delete LLM provider config",
        effect="destructive",
        idempotent=True,
        output=ProviderConfigDeletedOutput,
    )
    @requires_workspace_admin()
    async def delete_config(self, config_id: Annotated[str, Field(description=_CONFIG_ID)]) -> str:
        """Delete a provider configuration."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            service = _build_service(session, user_ctx, event_broker, secret_mgr)
            deleted = await service.delete_provider_config(UUID(config_id))
            return json.dumps({"deleted": deleted})
