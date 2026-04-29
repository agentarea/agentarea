"""ProvidersToolset — manage LLM provider configurations.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth is the Pydantic DTO ``ProviderConfigCreate`` /
``ProviderConfigUpdate`` in ``agentarea_llm.schemas.dto``. The contract
test in ``tests/unit/test_mcp_rest_parity.py`` enforces parity.
"""

import json
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_llm.schemas.dto import ProviderConfigCreate, ProviderConfigUpdate

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


@toolset(
    namespace="agentarea/providers",
    display_name="LLM Providers",
    description="Manage LLM provider specs and configurations.",
    category="platform",
)
class ProvidersToolset(Toolset):
    """Manage LLM providers: list specs, list/create/update/delete configurations."""

    @tool_method
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

    @tool_method
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

    @tool_method
    async def create_config(
        self,
        provider_spec_id: str,
        name: str,
        api_key: str,
        endpoint_url: str = "",
        description: str = "",
        is_public: bool = False,
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

    @tool_method
    async def update_config(
        self,
        config_id: str,
        name: str | None = None,
        api_key: str | None = None,
        endpoint_url: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        is_public: bool | None = None,
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
                return json.dumps({"error": "Provider configuration not found"})
            return json.dumps({"id": str(config.id), "name": config.name}, default=str)

    @tool_method
    async def delete_config(self, config_id: str) -> str:
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
