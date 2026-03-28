"""ProvidersToolset — manage LLM provider configurations."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context


class ProvidersToolset(Toolset):
    """Manage LLM providers: list specs, list/create/delete configurations."""

    @tool_method
    async def list_specs(self) -> str:
        """List available LLM provider specifications (e.g. OpenAI, Anthropic)."""
        async with platform_context() as (session, user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
            from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

            service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(session, user_ctx),
                provider_config_repo=ProviderConfigRepository(session, user_ctx),
                model_spec_repo=ModelSpecRepository(session, user_ctx),
                model_instance_repo=ModelInstanceRepository(session, user_ctx),
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            specs = await service.list_provider_specs()
            return json.dumps(
                [{"id": str(s.id), "name": s.name, "key": s.provider_key} for s in specs],
                default=str,
            )

    @tool_method
    async def list_configs(self) -> str:
        """List configured LLM provider connections."""
        async with platform_context() as (session, user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
            from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

            service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(session, user_ctx),
                provider_config_repo=ProviderConfigRepository(session, user_ctx),
                model_spec_repo=ModelSpecRepository(session, user_ctx),
                model_instance_repo=ModelInstanceRepository(session, user_ctx),
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
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
    ) -> str:
        """Create a new LLM provider configuration with API key."""
        from uuid import UUID

        async with platform_context() as (session, user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
            from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

            service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(session, user_ctx),
                provider_config_repo=ProviderConfigRepository(session, user_ctx),
                model_spec_repo=ModelSpecRepository(session, user_ctx),
                model_instance_repo=ModelInstanceRepository(session, user_ctx),
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            config = await service.create_provider_config(
                provider_spec_id=UUID(provider_spec_id),
                name=name,
                api_key=api_key,
                endpoint_url=endpoint_url or None,
                created_by=user_ctx.user_id,
            )
            return json.dumps({"id": str(config.id), "name": config.name}, default=str)

    @tool_method
    async def delete_config(self, config_id: str) -> str:
        """Delete a provider configuration."""
        from uuid import UUID

        async with platform_context() as (session, user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
            from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

            service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(session, user_ctx),
                provider_config_repo=ProviderConfigRepository(session, user_ctx),
                model_spec_repo=ModelSpecRepository(session, user_ctx),
                model_instance_repo=ModelInstanceRepository(session, user_ctx),
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            deleted = await service.delete_provider_config(UUID(config_id))
            return json.dumps({"deleted": deleted})
