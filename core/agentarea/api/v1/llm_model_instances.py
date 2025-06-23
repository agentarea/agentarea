from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agentarea.api.deps.services import get_llm_model_instance_service
from agentarea.modules.llm.application.service import LLMModelInstanceService
from agentarea.modules.llm.domain.models import LLMModelInstance

router = APIRouter(prefix="/llm-models/instances", tags=["llm-model-instances"])


class LLMModelInstanceCreate(BaseModel):
    model_id: UUID
    api_key: str
    name: str
    description: str
    is_public: bool = False


class LLMModelInstanceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    api_key: str | None = None
    is_public: bool | None = None
    status: str | None = None


class LLMModelInstanceResponse(BaseModel):
    id: UUID
    model_id: UUID
    name: str
    description: str
    status: str
    is_public: bool
    updated_at: datetime

    @classmethod
    def from_domain(cls, instance: LLMModelInstance) -> "LLMModelInstanceResponse":
        return cls(
            id=instance.id,
            model_id=instance.model_id,
            name=instance.name,
            description=instance.description,
            status=instance.status,
            is_public=instance.is_public,
            updated_at=instance.updated_at,
        )


@router.post("/", response_model=LLMModelInstanceResponse)
async def create_llm_model_instance(
    data: LLMModelInstanceCreate,
    llm_model_instance_service: LLMModelInstanceService = Depends(get_llm_model_instance_service),
):
    """Create a new LLM model instance."""
    instance = await llm_model_instance_service.create_llm_model_instance(
        model_id=data.model_id,
        api_key=data.api_key,
        name=data.name,
        description=data.description,
        is_public=data.is_public,
    )
    return LLMModelInstanceResponse.from_domain(instance)


@router.get("/{instance_id}", response_model=LLMModelInstanceResponse)
async def get_llm_model_instance(
    instance_id: UUID,
    llm_model_instance_service: LLMModelInstanceService = Depends(get_llm_model_instance_service),
):
    """Get an LLM model instance by ID."""
    instance = await llm_model_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="LLM Model Instance not found")
    return LLMModelInstanceResponse.from_domain(instance)


@router.get("/", response_model=list[LLMModelInstanceResponse])
async def list_llm_model_instances(
    model_id: UUID | None = None,
    status: str | None = None,
    is_public: bool | None = None,
    llm_model_instance_service: LLMModelInstanceService = Depends(get_llm_model_instance_service),
):
    """List LLM model instances with optional filters."""
    instances = await llm_model_instance_service.list(
        model_id=model_id, status=status, is_public=is_public
    )
    return [LLMModelInstanceResponse.from_domain(instance) for instance in instances]


@router.patch("/{instance_id}", response_model=LLMModelInstanceResponse)
async def update_llm_model_instance(
    instance_id: UUID,
    data: LLMModelInstanceUpdate,
    llm_model_instance_service: LLMModelInstanceService = Depends(get_llm_model_instance_service),
):
    """Update an LLM model instance."""
    instance = await llm_model_instance_service.update_llm_model_instance(
        id=instance_id,
        name=data.name,
        description=data.description,
        api_key=data.api_key,
        is_public=data.is_public,
        status=data.status,
    )
    if not instance:
        raise HTTPException(status_code=404, detail="LLM Model Instance not found")
    return LLMModelInstanceResponse.from_domain(instance)


@router.delete("/{instance_id}")
async def delete_llm_model_instance(
    instance_id: UUID,
    llm_model_instance_service: LLMModelInstanceService = Depends(get_llm_model_instance_service),
):
    """Delete an LLM model instance."""
    success = await llm_model_instance_service.delete_llm_model_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="LLM Model Instance not found")
    return {"status": "success"}


# Validation removed - LLM instances are validated when used by agent_runner_service
