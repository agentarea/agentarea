import logging
import re
from datetime import datetime
from uuid import UUID

from agentarea_api.api.deps.services import get_model_spec_repository, get_provider_service  # type: ignore
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_llm.application.model_discovery_service import ModelDiscoveryService
from agentarea_llm.application.provider_service import ProviderService  # type: ignore
from agentarea_llm.domain.models import ProviderConfig  # type: ignore
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/provider-configs", tags=["provider-configs"])


# Provider Config schemas
class ProviderConfigCreate(BaseModel):
    provider_spec_id: UUID
    name: str
    api_key: str
    endpoint_url: str | None = None
    is_public: bool = False


class ProviderConfigUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    endpoint_url: str | None = None
    is_active: bool | None = None


class ProviderConfigResponse(BaseModel):
    id: str
    provider_spec_id: str
    name: str
    endpoint_url: str | None
    workspace_id: str
    created_by: str
    is_active: bool
    is_public: bool
    created_at: datetime
    updated_at: datetime

    # Related data
    provider_spec_name: str | None = None
    provider_spec_key: str | None = None
    model_instance_ids: list[str] = []

    @classmethod
    def from_domain(cls, provider_config: ProviderConfig) -> "ProviderConfigResponse":
        # Extract model instance IDs from the relationship if loaded
        # Always return a list (empty if no model instances)
        model_instance_ids: list[str] = []
        if (
            hasattr(provider_config, "model_instances")
            and provider_config.model_instances is not None
        ):
            model_instance_ids = [
                str(instance.model_spec_id) for instance in provider_config.model_instances
            ]

        return cls(
            id=str(provider_config.id),
            provider_spec_id=str(provider_config.provider_spec_id),
            name=provider_config.name,
            endpoint_url=provider_config.endpoint_url,
            workspace_id=provider_config.workspace_id,
            created_by=provider_config.created_by,
            is_active=provider_config.is_active,
            is_public=provider_config.is_public,
            created_at=provider_config.created_at,
            updated_at=provider_config.updated_at,
            provider_spec_name=provider_config.provider_spec.name
            if hasattr(provider_config, "provider_spec") and provider_config.provider_spec
            else None,
            provider_spec_key=provider_config.provider_spec.provider_key
            if hasattr(provider_config, "provider_spec") and provider_config.provider_spec
            else None,
            model_instance_ids=model_instance_ids,
        )


class ModelInstanceResponse(BaseModel):
    id: str
    provider_config_id: str
    model_spec_id: str
    name: str
    description: str | None
    is_active: bool
    is_public: bool
    created_at: datetime
    updated_at: datetime

    # Related data
    provider_name: str | None = None
    provider_key: str | None = None
    model_name: str | None = None
    model_display_name: str | None = None
    config_name: str | None = None

    @classmethod
    def from_domain(cls, model_instance) -> "ModelInstanceResponse":
        return cls(
            id=str(model_instance.id),
            provider_config_id=str(model_instance.provider_config_id),
            model_spec_id=str(model_instance.model_spec_id),
            name=model_instance.name,
            description=model_instance.description,
            is_active=model_instance.is_active,
            is_public=model_instance.is_public,
            created_at=model_instance.created_at,
            updated_at=model_instance.updated_at,
            provider_name=model_instance.provider_config.provider_spec.name
            if model_instance.provider_config and model_instance.provider_config.provider_spec
            else None,
            provider_key=model_instance.provider_config.provider_spec.provider_key
            if model_instance.provider_config and model_instance.provider_config.provider_spec
            else None,
            model_name=model_instance.model_spec.model_name if model_instance.model_spec else None,
            model_display_name=model_instance.model_spec.display_name
            if model_instance.model_spec
            else None,
            config_name=model_instance.provider_config.name
            if model_instance.provider_config
            else None,
        )


class ProviderConfigWithInstancesResponse(BaseModel):
    id: str
    provider_spec_id: str
    name: str
    endpoint_url: str | None
    user_id: str | None
    is_active: bool
    is_public: bool
    created_at: datetime
    updated_at: datetime

    # Related data
    provider_spec_name: str | None = None
    provider_spec_key: str | None = None
    model_instances: list[ModelInstanceResponse] = []

    @classmethod
    def from_domain(cls, provider_config: ProviderConfig) -> "ProviderConfigWithInstancesResponse":
        return cls(
            id=str(provider_config.id),
            provider_spec_id=str(provider_config.provider_spec_id),
            name=provider_config.name,
            endpoint_url=provider_config.endpoint_url,
            user_id=str(provider_config.user_id) if provider_config.user_id else None,
            is_active=provider_config.is_active,
            is_public=provider_config.is_public,
            created_at=provider_config.created_at,
            updated_at=provider_config.updated_at,
            provider_spec_name=provider_config.provider_spec.name
            if hasattr(provider_config, "provider_spec") and provider_config.provider_spec
            else None,
            provider_spec_key=provider_config.provider_spec.provider_key
            if hasattr(provider_config, "provider_spec") and provider_config.provider_spec
            else None,
            model_instances=[
                ModelInstanceResponse.from_domain(instance)
                for instance in provider_config.model_instances
            ]
            if hasattr(provider_config, "model_instances") and provider_config.model_instances
            else [],
        )


# Provider Config endpoints


@router.post("/", response_model=ProviderConfigResponse)
async def create_provider_config(
    data: ProviderConfigCreate,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Create a new provider configuration."""
    config = await provider_service.create_provider_config(
        provider_spec_id=data.provider_spec_id,
        name=data.name,
        api_key=data.api_key,
        endpoint_url=data.endpoint_url,
        created_by=str(user_context.user_id),
        is_public=data.is_public,
    )
    return ProviderConfigResponse.from_domain(config)


@router.get("/", response_model=list[ProviderConfigResponse])
async def list_provider_configs(
    user_context: UserContextDep,
    provider_spec_id: UUID | None = None,
    is_active: bool | None = None,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """List provider configurations."""
    configs = await provider_service.list_provider_configs(
        provider_spec_id=provider_spec_id,
        is_active=is_active,
    )
    return [ProviderConfigResponse.from_domain(config) for config in configs]


@router.get("/with-instances", response_model=list[ProviderConfigResponse])
async def list_provider_configs_with_instances(
    user_context: UserContextDep,
    provider_spec_id: UUID | None = None,
    is_active: bool | None = None,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """List provider configurations with their model instances."""
    configs = await provider_service.list_provider_configs(
        provider_spec_id=provider_spec_id,
        is_active=is_active,
    )
    return [ProviderConfigResponse.from_domain(config) for config in configs]


# Discover preview endpoint (no saved config required)
class DiscoverPreviewRequest(BaseModel):
    provider_key: str
    api_key: str
    endpoint_url: str | None = None


class DiscoverPreviewModelResponse(BaseModel):
    id: str
    model_name: str
    display_name: str
    context_window: int
    max_output_tokens: int = 4096
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    description: str | None = None
    is_new: bool = False


class DiscoverPreviewResponse(BaseModel):
    discovered: int
    new_models: int
    models: list[DiscoverPreviewModelResponse]


@router.post("/discover-preview", response_model=DiscoverPreviewResponse)
async def discover_models_preview(
    data: DiscoverPreviewRequest,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Discover models from a provider API using the provided API key, without requiring a saved config."""
    provider_spec = await provider_service.get_provider_spec_by_key(data.provider_key)
    if not provider_spec:
        raise HTTPException(status_code=404, detail=f"Provider '{data.provider_key}' not found")

    provider_spec_id = str(provider_spec.id)

    discovery_service = ModelDiscoveryService()
    discovered = await discovery_service.discover(
        provider_key=data.provider_key,
        api_key=data.api_key,
        endpoint_url=data.endpoint_url,
    )

    if not discovered:
        raise HTTPException(
            status_code=400,
            detail=f"No models discovered for provider '{data.provider_key}'. "
            "The provider may not support model listing or the API key may be invalid.",
        )

    results = []
    new_count = 0
    for model in discovered:
        existing = await model_spec_repo.get_by_provider_and_model(
            provider_spec_id, model.model_name
        )
        is_new = existing is None

        await model_spec_repo.upsert_by_provider_and_model_kwargs(
            provider_spec_id=provider_spec_id,
            model_name=model.model_name,
            display_name=model.display_name or model.model_name,
            description=model.description or None,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            input_cost_per_token=model.input_cost_per_token,
            output_cost_per_token=model.output_cost_per_token,
            supports_function_calling=model.supports_function_calling,
            supports_vision=model.supports_vision,
            supports_reasoning=model.supports_reasoning,
        )

        if is_new:
            new_count += 1

        results.append(DiscoverPreviewModelResponse(
            id=str(spec.id),
            model_name=model.model_name,
            display_name=model.display_name or model.model_name,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            input_cost_per_token=model.input_cost_per_token,
            output_cost_per_token=model.output_cost_per_token,
            supports_function_calling=model.supports_function_calling,
            supports_vision=model.supports_vision,
            supports_reasoning=model.supports_reasoning,
            description=model.description or None,
            is_new=is_new,
        ))

    logger.info(
        "Discovery preview for provider %s: %d found, %d new",
        data.provider_key, len(results), new_count,
    )

    return DiscoverPreviewResponse(
        discovered=len(results),
        new_models=new_count,
        models=results,
    )


@router.get("/{config_id}", response_model=ProviderConfigResponse)
async def get_provider_config(
    config_id: UUID,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Get a specific provider configuration."""
    config = await provider_service.get_provider_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Provider configuration not found")
    return ProviderConfigResponse.from_domain(config)


@router.put("/{config_id}", response_model=ProviderConfigResponse)
async def update_provider_config(
    config_id: UUID,
    data: ProviderConfigUpdate,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Update a provider configuration."""
    config = await provider_service.update_provider_config(
        config_id=config_id,
        name=data.name,
        api_key=data.api_key,
        endpoint_url=data.endpoint_url,
        is_active=data.is_active,
    )
    if not config:
        raise HTTPException(status_code=404, detail="Provider configuration not found")
    return ProviderConfigResponse.from_domain(config)


@router.delete("/{config_id}")
async def delete_provider_config(
    config_id: UUID,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Delete a provider configuration."""
    success = await provider_service.delete_provider_config(config_id)
    if not success:
        raise HTTPException(status_code=404, detail="Provider configuration not found")
    return {"message": "Provider configuration deleted successfully"}


# Discovery endpoint
class DiscoveredModelResponse(BaseModel):
    model_name: str
    display_name: str
    context_window: int
    max_output_tokens: int = 4096
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    description: str | None = None
    is_new: bool = False


class DiscoveryResponse(BaseModel):
    discovered: int
    new_models: int
    models: list[DiscoveredModelResponse]


@router.post("/{config_id}/discover", response_model=DiscoveryResponse)
async def discover_models(
    config_id: UUID,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Discover available models from the provider API and sync to model specs."""
    config = await provider_service.get_provider_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Provider configuration not found")

    # Get API key from secret manager
    secret_name = f"provider_config_{config.id}"
    api_key = await provider_service.secret_manager.get_secret(secret_name)
    if not api_key:
        raise HTTPException(status_code=400, detail="No API key found for this configuration")

    provider_key = config.provider_spec.provider_key
    provider_spec_id = str(config.provider_spec_id)

    discovery_service = ModelDiscoveryService()
    discovered = await discovery_service.discover(
        provider_key=provider_key,
        api_key=api_key,
        endpoint_url=config.endpoint_url,
    )

    if not discovered:
        raise HTTPException(
            status_code=400,
            detail=f"No models discovered for provider '{provider_key}'. "
            "The provider may not support model listing or the API key may be invalid.",
        )

    # Upsert discovered models as ModelSpec entries
    results = []
    new_count = 0
    for model in discovered:
        # Check if model already exists
        existing = await model_spec_repo.get_by_provider_and_model(
            provider_spec_id, model.model_name
        )
        is_new = existing is None

        await model_spec_repo.upsert_by_provider_and_model_kwargs(
            provider_spec_id=provider_spec_id,
            model_name=model.model_name,
            display_name=model.display_name or model.model_name,
            description=model.description or None,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            input_cost_per_token=model.input_cost_per_token,
            output_cost_per_token=model.output_cost_per_token,
            supports_function_calling=model.supports_function_calling,
            supports_vision=model.supports_vision,
            supports_reasoning=model.supports_reasoning,
        )

        if is_new:
            new_count += 1

        results.append(DiscoveredModelResponse(
            model_name=model.model_name,
            display_name=model.display_name or model.model_name,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            input_cost_per_token=model.input_cost_per_token,
            output_cost_per_token=model.output_cost_per_token,
            supports_function_calling=model.supports_function_calling,
            supports_vision=model.supports_vision,
            supports_reasoning=model.supports_reasoning,
            description=model.description or None,
            is_new=is_new,
        ))

    logger.info(
        "Discovery for provider %s: %d found, %d new",
        provider_key, len(results), new_count,
    )

    return DiscoveryResponse(
        discovered=len(results),
        new_models=new_count,
        models=results,
    )


# Logo/Icon endpoints
@router.get("/admin/{provider_key}/logo")
async def get_provider_logo(
    provider_key: str,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Get provider logo via admin route pattern."""
    # Sanitize provider_key to prevent path traversal
    if not re.match(r"^[a-zA-Z0-9_-]+$", provider_key):
        raise HTTPException(status_code=400, detail="Invalid provider key")

    import os

    from fastapi.responses import FileResponse

    # Map provider key to icon file
    icon_path = f"core/static/icons/providers/{provider_key.lower()}.svg"

    if os.path.exists(icon_path):
        return FileResponse(
            icon_path, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"}
        )

    # Return default icon if specific one doesn't exist
    default_path = "core/static/icons/providers/default.svg"
    if os.path.exists(default_path):
        return FileResponse(
            default_path,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    raise HTTPException(status_code=404, detail="Provider logo not found")
