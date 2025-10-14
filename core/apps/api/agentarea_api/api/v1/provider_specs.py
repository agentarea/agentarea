from datetime import datetime
from uuid import UUID

from agentarea_api.api.deps.services import get_provider_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.domain.models import ModelSpec, ProviderSpec
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/provider-specs", tags=["provider-specs"])


# Provider Spec schemas
class ProviderSpecResponse(BaseModel):
    id: str
    provider_key: str
    name: str
    description: str | None
    provider_type: str
    icon: str | None
    icon_url: str | None
    is_builtin: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(
        cls, provider_spec: ProviderSpec, request: Request | None = None
    ) -> "ProviderSpecResponse":
        icon_url = None
        if provider_spec.icon and request:
            base_url = str(request.base_url).rstrip("/")
            icon_url = f"{base_url}/static/icons/providers/{provider_spec.icon}.svg"

        return cls(
            id=str(provider_spec.id),
            provider_key=provider_spec.provider_key,
            name=provider_spec.name,
            description=provider_spec.description,
            provider_type=provider_spec.provider_type,
            icon=provider_spec.icon,
            icon_url=icon_url,
            is_builtin=provider_spec.is_builtin,
            created_at=provider_spec.created_at,
            updated_at=provider_spec.updated_at,
        )


class ModelSpecResponse(BaseModel):
    id: str
    provider_spec_id: str
    model_name: str
    display_name: str
    description: str | None
    context_window: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, model_spec: ModelSpec) -> "ModelSpecResponse":
        return cls(
            id=str(model_spec.id),
            provider_spec_id=str(model_spec.provider_spec_id),
            model_name=model_spec.model_name,
            display_name=model_spec.display_name,
            description=model_spec.description,
            context_window=model_spec.context_window,
            is_active=model_spec.is_active,
            created_at=model_spec.created_at,
            updated_at=model_spec.updated_at,
        )


class ProviderSpecWithModelsResponse(BaseModel):
    id: str
    provider_key: str
    name: str
    description: str | None
    provider_type: str
    icon: str | None
    icon_url: str | None
    is_builtin: bool
    created_at: datetime
    updated_at: datetime
    models: list[ModelSpecResponse]

    @classmethod
    def from_domain(
        cls, provider_spec: ProviderSpec, request: Request | None = None
    ) -> "ProviderSpecWithModelsResponse":
        icon_url = None
        if provider_spec.icon and request:
            base_url = str(request.base_url).rstrip("/")
            icon_url = f"{base_url}/static/icons/providers/{provider_spec.icon}.svg"

        return cls(
            id=str(provider_spec.id),
            provider_key=provider_spec.provider_key,
            name=provider_spec.name,
            description=provider_spec.description,
            provider_type=provider_spec.provider_type,
            icon=provider_spec.icon,
            icon_url=icon_url,
            is_builtin=provider_spec.is_builtin,
            created_at=provider_spec.created_at,
            updated_at=provider_spec.updated_at,
            models=[ModelSpecResponse.from_domain(model) for model in provider_spec.model_specs],
        )


# Provider Spec endpoints
@router.get("/", response_model=list[ProviderSpecResponse])
async def list_provider_specs(
    request: Request,
    user_context: UserContextDep,
    is_builtin: bool | None = None,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """List all provider specifications."""
    provider_specs = await provider_service.list_provider_specs(is_builtin=is_builtin)
    return [ProviderSpecResponse.from_domain(spec, request) for spec in provider_specs]


@router.get("/with-models", response_model=list[ProviderSpecWithModelsResponse])
async def list_provider_specs_with_models(
    request: Request,
    user_context: UserContextDep,
    is_builtin: bool | None = None,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """List all provider specifications with their available models."""
    provider_specs = await provider_service.list_provider_specs(is_builtin=is_builtin)
    return [ProviderSpecWithModelsResponse.from_domain(spec, request) for spec in provider_specs]


@router.get("/{provider_spec_id}", response_model=ProviderSpecWithModelsResponse)
async def get_provider_spec(
    provider_spec_id: UUID,
    request: Request,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Get a specific provider specification with its models."""
    provider_spec = await provider_service.get_provider_spec(provider_spec_id)
    if not provider_spec:
        raise HTTPException(status_code=404, detail="Provider specification not found")
    return ProviderSpecWithModelsResponse.from_domain(provider_spec, request)


@router.get("/by-key/{provider_key}", response_model=ProviderSpecWithModelsResponse)
async def get_provider_spec_by_key(
    provider_key: str,
    request: Request,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Get a provider specification by its key (e.g., 'openai', 'anthropic')."""
    provider_spec = await provider_service.get_provider_spec_by_key(provider_key)
    if not provider_spec:
        raise HTTPException(status_code=404, detail="Provider specification not found")
    return ProviderSpecWithModelsResponse.from_domain(provider_spec, request)
