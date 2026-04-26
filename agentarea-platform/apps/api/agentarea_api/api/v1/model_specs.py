from datetime import datetime
from uuid import UUID

from agentarea_api.api.deps.services import get_model_spec_repository
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_llm.domain.models import ModelSpec
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/model-specs", tags=["model-specs"])


# Model Spec schemas
class ModelSpecCreate(BaseModel):
    provider_spec_id: UUID
    model_name: str
    display_name: str
    description: str | None = None
    context_window: int = 4096
    default_context_strategy: str | None = None  # Auto-inferred from model_name if None
    is_active: bool = True


class ModelSpecUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    context_window: int | None = None
    default_context_strategy: str | None = None
    is_active: bool | None = None


class ModelSpecResponse(BaseModel):
    id: str
    provider_spec_id: str
    model_name: str
    display_name: str
    description: str | None
    context_window: int
    max_output_tokens: int | None = 4096
    input_cost_per_token: float | None = 0.0
    output_cost_per_token: float | None = 0.0
    supports_function_calling: bool | None = False
    supports_vision: bool | None = False
    supports_reasoning: bool | None = False
    default_context_strategy: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # Related provider info (if loaded)
    provider_name: str | None = None
    provider_key: str | None = None

    @classmethod
    def from_domain(cls, model_spec: ModelSpec) -> "ModelSpecResponse":
        return cls(
            id=str(model_spec.id),
            provider_spec_id=str(model_spec.provider_spec_id),
            model_name=model_spec.model_name,
            display_name=model_spec.display_name,
            description=model_spec.description,
            context_window=model_spec.context_window,
            max_output_tokens=model_spec.max_output_tokens,
            input_cost_per_token=model_spec.input_cost_per_token,
            output_cost_per_token=model_spec.output_cost_per_token,
            supports_function_calling=model_spec.supports_function_calling,
            supports_vision=model_spec.supports_vision,
            supports_reasoning=model_spec.supports_reasoning,
            default_context_strategy=model_spec.default_context_strategy,
            is_active=model_spec.is_active,
            created_at=model_spec.created_at,
            updated_at=model_spec.updated_at,
            provider_name=model_spec.provider_spec.name if model_spec.provider_spec else None,
            provider_key=model_spec.provider_spec.provider_key
            if model_spec.provider_spec
            else None,
        )


# Model Spec endpoints
@router.get("/", response_model=list[ModelSpecResponse])
async def list_model_specs(
    user_context: UserContextDep,
    provider_spec_id: UUID | None = None,
    is_active: bool | None = None,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """List model specifications with optional filtering."""
    model_specs = await model_spec_repo.list(
        provider_spec_id=provider_spec_id,
        is_active=is_active,
    )
    return [ModelSpecResponse.from_domain(spec) for spec in model_specs]


@router.get("/{model_spec_id}", response_model=ModelSpecResponse)
async def get_model_spec(
    model_spec_id: UUID,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Get a specific model specification by ID."""
    model_spec = await model_spec_repo.get(model_spec_id)
    if not model_spec:
        raise HTTPException(status_code=404, detail="Model specification not found")
    return ModelSpecResponse.from_domain(model_spec)


@router.get("/by-provider/{provider_spec_id}", response_model=list[ModelSpecResponse])
async def list_model_specs_by_provider(
    provider_spec_id: UUID,
    user_context: UserContextDep,
    is_active: bool | None = None,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """List all model specifications for a specific provider."""
    model_specs = await model_spec_repo.list(
        provider_spec_id=provider_spec_id,
        is_active=is_active,
    )
    return [ModelSpecResponse.from_domain(spec) for spec in model_specs]


@router.get("/by-provider/{provider_spec_id}/{model_name}", response_model=ModelSpecResponse)
async def get_model_spec_by_provider_and_name(
    provider_spec_id: UUID,
    model_name: str,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Get a specific model specification by provider and model name."""
    model_spec = await model_spec_repo.get_by_provider_and_model(provider_spec_id, model_name)
    if not model_spec:
        raise HTTPException(
            status_code=404, detail=f"Model specification '{model_name}' not found for provider"
        )
    return ModelSpecResponse.from_domain(model_spec)


@router.post("/", response_model=ModelSpecResponse)
async def create_model_spec(
    data: ModelSpecCreate,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Create a new model specification."""
    existing = await model_spec_repo.get_by_provider_and_model(
        data.provider_spec_id, data.model_name
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Model specification '{data.model_name}' already exists for this provider",
        )

    try:
        created_spec = await model_spec_repo.create(
            provider_spec_id=str(data.provider_spec_id),
            model_name=data.model_name,
            display_name=data.display_name,
            description=data.description,
            context_window=data.context_window,
            default_context_strategy=data.default_context_strategy,
            is_active=data.is_active,
        )
    except IntegrityError:
        # Concurrent insert raced past the pre-check and tripped the
        # uq_model_specs_provider_model unique constraint.
        raise HTTPException(
            status_code=409,
            detail=f"Model specification '{data.model_name}' already exists for this provider",
        ) from None
    return ModelSpecResponse.from_domain(created_spec)


@router.patch("/{model_spec_id}", response_model=ModelSpecResponse)
async def update_model_spec(
    model_spec_id: UUID,
    data: ModelSpecUpdate,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Update a model specification."""
    model_spec = await model_spec_repo.get(model_spec_id)
    if not model_spec:
        raise HTTPException(status_code=404, detail="Model specification not found")

    # Update fields if provided
    if data.display_name is not None:
        model_spec.display_name = data.display_name
    if data.description is not None:
        model_spec.description = data.description
    if data.context_window is not None:
        model_spec.context_window = data.context_window
    if data.default_context_strategy is not None:
        model_spec.default_context_strategy = data.default_context_strategy
    if data.is_active is not None:
        model_spec.is_active = data.is_active

    updated_spec = await model_spec_repo.update(model_spec)
    return ModelSpecResponse.from_domain(updated_spec)


@router.delete("/{model_spec_id}")
async def delete_model_spec(
    model_spec_id: UUID,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Delete a model specification."""
    success = await model_spec_repo.delete(model_spec_id)
    if not success:
        raise HTTPException(status_code=404, detail="Model specification not found")
    return {"message": "Model specification deleted successfully"}


@router.post("/upsert", response_model=ModelSpecResponse)
async def upsert_model_spec(
    data: ModelSpecCreate,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Create or update a model specification by provider and model name.

    This endpoint is useful for bulk operations and bootstrapping.
    """
    upserted_spec = await model_spec_repo.upsert_by_provider_and_model_kwargs(
        provider_spec_id=str(data.provider_spec_id),
        model_name=data.model_name,
        display_name=data.display_name,
        description=data.description,
        context_window=data.context_window,
        default_context_strategy=data.default_context_strategy,
        is_active=data.is_active,
    )
    return ModelSpecResponse.from_domain(upserted_spec)
