"""ModelsToolset — inspect model specs and manage model instances."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset

from .base import platform_context


@toolset(
    namespace="agentarea/models",
    display_name="Models",
    description="Inspect model specifications and create/inspect model instances.",
    category="platform",
)
class ModelsToolset(Toolset):
    """Inspect available model specs and manage the workspace's model instances."""

    @tool_method
    async def list_specs(self) -> str:
        """List available model specifications (e.g. gpt-4o, claude-sonnet)."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import (
                ModelInstanceRepository,
            )
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import (
                ProviderConfigRepository,
            )
            from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

            service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(session, user_ctx),
                provider_config_repo=ProviderConfigRepository(session, user_ctx),
                model_spec_repo=ModelSpecRepository(session, user_ctx),
                model_instance_repo=ModelInstanceRepository(session, user_ctx),
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            specs = await service.list_model_specs()
            return json.dumps(
                [
                    {
                        "id": str(s.id),
                        "name": s.display_name or s.model_name,
                        "provider_spec_id": str(s.provider_spec_id),
                    }
                    for s in specs
                ],
                default=str,
            )

    @tool_method
    async def list_instances(self) -> str:
        """List configured model instances (models connected to provider configs)."""
        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import (
                ModelInstanceRepository,
            )
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import (
                ProviderConfigRepository,
            )
            from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

            service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(session, user_ctx),
                provider_config_repo=ProviderConfigRepository(session, user_ctx),
                model_spec_repo=ModelSpecRepository(session, user_ctx),
                model_instance_repo=ModelInstanceRepository(session, user_ctx),
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instances = await service.list_model_instances()
            return json.dumps(
                [
                    {
                        "id": str(m.id),
                        "name": m.name,
                        "model_spec_id": str(m.model_spec_id),
                        "provider_config_id": str(m.provider_config_id),
                        "is_active": m.is_active,
                    }
                    for m in instances
                ],
                default=str,
            )

    @tool_method
    async def create_instance(
        self,
        provider_config_id: str,
        model_spec_id: str,
        name: str,
        description: str = "",
    ) -> str:
        """Connect a model spec to a provider config, making it usable by agents.

        An agent's model_id must be the id of a model instance, so this is the
        step between configuring a provider and creating a working agent. Pick
        provider_config_id from providers_list_configs and model_spec_id from
        list_specs (the spec must belong to that provider).
        """
        from uuid import UUID

        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import (
                ModelInstanceRepository,
            )
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import (
                ProviderConfigRepository,
            )
            from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

            service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(session, user_ctx),
                provider_config_repo=ProviderConfigRepository(session, user_ctx),
                model_spec_repo=ModelSpecRepository(session, user_ctx),
                model_instance_repo=ModelInstanceRepository(session, user_ctx),
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instance = await service.create_model_instance(
                provider_config_id=UUID(provider_config_id),
                model_spec_id=UUID(model_spec_id),
                name=name,
                description=description or None,
            )
            return json.dumps(
                {
                    "id": str(instance.id),
                    "name": instance.name,
                    "model_spec_id": str(instance.model_spec_id),
                    "provider_config_id": str(instance.provider_config_id),
                    "is_active": instance.is_active,
                },
                default=str,
            )

    @tool_method
    async def get(self, model_instance_id: str) -> str:
        """Get details of a model instance."""
        from uuid import UUID

        async with platform_context() as (
            session,
            user_ctx,
            _repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import (
                ModelInstanceRepository,
            )
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import (
                ProviderConfigRepository,
            )
            from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

            service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(session, user_ctx),
                provider_config_repo=ProviderConfigRepository(session, user_ctx),
                model_spec_repo=ModelSpecRepository(session, user_ctx),
                model_instance_repo=ModelInstanceRepository(session, user_ctx),
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instance = await service.get_model_instance(UUID(model_instance_id))
            if not instance:
                return json.dumps({"error": "Model instance not found"})
            return json.dumps(
                {
                    "id": str(instance.id),
                    "name": instance.name,
                    "model_spec_id": str(instance.model_spec_id),
                    "provider_config_id": str(instance.provider_config_id),
                    "is_active": instance.is_active,
                },
                default=str,
            )
