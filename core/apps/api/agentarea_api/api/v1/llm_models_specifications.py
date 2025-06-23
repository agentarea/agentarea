from datetime import datetime
from uuid import UUID

from agentarea_api.api.deps.services import get_llm_model_service
from agentarea_llm.application.llm_model_service import LLMModelService
from agentarea_llm.domain.models import LLMModel
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/llm-models", tags=["llm-models"])


# LLM Model schemas
class LLMModelCreate(BaseModel):
    name: str
    description: str
    provider: str
    model_type: str
    endpoint_url: str
    context_window: str
    is_public: bool = False


class LLMModelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    provider: str | None = None
    model_type: str | None = None
    endpoint_url: str | None = None
    context_window: str | None = None
    is_public: bool | None = None
    status: str | None = None


class LLMModelResponse(BaseModel):
    id: str
    name: str
    description: str
    provider: str
    model_type: str
    endpoint_url: str
    context_window: str
    status: str
    is_public: bool
    updated_at: datetime

    @classmethod
    def from_domain(cls, model: LLMModel) -> "LLMModelResponse":
        return cls(
            id=str(model.id),
            name=model.name,
            description=model.description,
            provider=model.provider.name if model.provider else "",
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
    """Create a new LLM model."""
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
    model_id: str, llm_model_service: LLMModelService = Depends(get_llm_model_service)
):
    try:
        model_uuid = UUID(model_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid model ID format: {model_id}"
        ) from None

    model = await llm_model_service.get(model_uuid)
    if not model:
        raise HTTPException(status_code=404, detail="LLM Model not found")
    return LLMModelResponse.from_domain(model)


@router.get("/", response_model=list[LLMModelResponse])
async def list_llm_models(
    status: str | None = None,
    is_public: bool | None = None,
    provider: str | None = None,
    llm_model_service: LLMModelService = Depends(get_llm_model_service),
):
    models = await llm_model_service.list(status=status, is_public=is_public, provider=provider)
    return [LLMModelResponse.from_domain(model) for model in models]


@router.patch("/{model_id}", response_model=LLMModelResponse)
async def update_llm_model(
    model_id: str,
    data: LLMModelUpdate,
    llm_model_service: LLMModelService = Depends(get_llm_model_service),
):
    try:
        model_uuid = UUID(model_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid model ID format: {model_id}"
        ) from None

    model = await llm_model_service.update_llm_model(
        id=model_uuid,
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
    model_id: str, llm_model_service: LLMModelService = Depends(get_llm_model_service)
):
    try:
        model_uuid = UUID(model_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid model ID format: {model_id}"
        ) from None

    success = await llm_model_service.delete_llm_model(model_uuid)
    if not success:
        raise HTTPException(status_code=404, detail="LLM Model not found")
    return {"status": "success"}
