from datetime import datetime
from uuid import UUID

from agentarea_api.api.deps.services import get_provider_service
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.domain.models import ModelInstance
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/model-instances", tags=["model-instances"])


# Model Instance schemas
class ModelInstanceCreate(BaseModel):
    provider_config_id: UUID
    model_spec_id: UUID
    name: str
    description: str | None = None
    is_public: bool = False


class ModelInstanceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    is_public: bool | None = None


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
    def from_domain(cls, model_instance: ModelInstance) -> "ModelInstanceResponse":
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
            provider_name=model_instance.provider_config.provider_spec.name if model_instance.provider_config and model_instance.provider_config.provider_spec else None,
            provider_key=model_instance.provider_config.provider_spec.provider_key if model_instance.provider_config and model_instance.provider_config.provider_spec else None,
            model_name=model_instance.model_spec.model_name if model_instance.model_spec else None,
            model_display_name=model_instance.model_spec.display_name if model_instance.model_spec else None,
            config_name=model_instance.provider_config.name if model_instance.provider_config else None,
        )


# Model Instance endpoints
@router.post("/", response_model=ModelInstanceResponse)
async def create_model_instance(
    data: ModelInstanceCreate,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Create a new model instance."""
    instance = await provider_service.create_model_instance(
        provider_config_id=data.provider_config_id,
        model_spec_id=data.model_spec_id,
        name=data.name,
        description=data.description,
        is_public=data.is_public,
    )
    return ModelInstanceResponse.from_domain(instance)


@router.get("/", response_model=list[ModelInstanceResponse])
async def list_model_instances(
    provider_config_id: UUID | None = None,
    model_spec_id: UUID | None = None,
    is_active: bool | None = None,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """List model instances."""
    instances = await provider_service.list_model_instances(
        provider_config_id=provider_config_id,
        model_spec_id=model_spec_id,
        is_active=is_active,
    )
    return [ModelInstanceResponse.from_domain(instance) for instance in instances]


@router.get("/{instance_id}", response_model=ModelInstanceResponse)
async def get_model_instance(
    instance_id: UUID,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Get a specific model instance."""
    instance = await provider_service.get_model_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Model instance not found")
    return ModelInstanceResponse.from_domain(instance)


@router.delete("/{instance_id}")
async def delete_model_instance(
    instance_id: UUID,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Delete a model instance."""
    success = await provider_service.delete_model_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="Model instance not found")
    return {"message": "Model instance deleted successfully"} 