from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl

from agentarea.modules.llm.application.service import LLMModelService
from agentarea.modules.llm.domain.models import LLMModel
from agentarea.api.deps.services import get_llm_model_service

router = APIRouter(prefix="/llm-models", tags=["llm-models"])


# LLM Model schemas
class LLMModelCreate(BaseModel):
    name: str
    description: str
    provider: str
    model_type: str
    endpoint_url: HttpUrl
    context_window: str
    is_public: bool = False


class LLMModelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    provider: str | None = None
    model_type: str | None = None
    endpoint_url: HttpUrl | None = None
    context_window: str | None = None
    is_public: bool | None = None
    status: str | None = None


class LLMModelResponse(BaseModel):
    id: UUID
    name: str
    description: str
    provider: str
    model_type: str
    endpoint_url: HttpUrl
    context_window: str
    status: str
    is_public: bool
    updated_at: str

    @classmethod
    def from_domain(cls, model: LLMModel) -> "LLMModelResponse":
        return cls(
            id=model.id,
            name=model.name,
            description=model.description,
            provider=model.provider,
            model_type=model.model_type,
            endpoint_url=model.endpoint_url,
            context_window=model.context_window,
            status=model.status,
            is_public=model.is_public,
            updated_at=model.updated_at,
        )


# LLM Model endpoints
@router.post("/", response_model=LLMModelResponse)
async def create_llm_model(
    data: LLMModelCreate,
    llm_model_service: LLMModelService = Depends(get_llm_model_service),
):
    model = await llm_model_service.create_llm_model(
        name=data.name,
        description=data.description,
        provider=data.provider,
        model_type=data.model_type,
        endpoint_url=data.endpoint_url,
        context_window=data.context_window,
        is_public=data.is_public,
    )
    return LLMModelResponse.from_domain(model)


@router.get("/{model_id}", response_model=LLMModelResponse)
async def get_llm_model(
    model_id: UUID, llm_model_service: LLMModelService = Depends(get_llm_model_service)
):
    model = await llm_model_service.get(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="LLM Model not found")
    return LLMModelResponse.from_domain(model)


@router.get("/", response_model=List[LLMModelResponse])
async def list_llm_models(
    status: Optional[str] = None,
    is_public: Optional[bool] = None,
    provider: Optional[str] = None,
    llm_model_service: LLMModelService = Depends(get_llm_model_service),
):
    models = await llm_model_service.list(
        status=status, is_public=is_public, provider=provider
    )
    return [LLMModelResponse.from_domain(model) for model in models]


@router.patch("/{model_id}", response_model=LLMModelResponse)
async def update_llm_model(
    model_id: UUID,
    data: LLMModelUpdate,
    llm_model_service: LLMModelService = Depends(get_llm_model_service),
):
    model = await llm_model_service.update_llm_model(
        id=model_id,
        name=data.name,
        description=data.description,
        provider=data.provider,
        model_type=data.model_type,
        endpoint_url=data.endpoint_url,
        context_window=data.context_window,
        is_public=data.is_public,
        status=data.status,
    )
    if not model:
        raise HTTPException(status_code=404, detail="LLM Model not found")
    return LLMModelResponse.from_domain(model)


@router.delete("/{model_id}")
async def delete_llm_model(
    model_id: UUID, llm_model_service: LLMModelService = Depends(get_llm_model_service)
):
    success = await llm_model_service.delete_llm_model(model_id)
    if not success:
        raise HTTPException(status_code=404, detail="LLM Model not found")
    return {"status": "success"}
