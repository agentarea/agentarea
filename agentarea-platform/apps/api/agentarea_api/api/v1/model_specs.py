from decimal import Decimal
from uuid import UUID

from agentarea_api.api.deps.services import get_model_spec_repository, get_model_spec_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import requires_workspace_admin, unrestricted
from agentarea_common.money import ZERO, Money
from agentarea_common.utils.types import UtcDatetime
from agentarea_llm.application.model_spec_service import ModelSpecService
from agentarea_llm.domain.models import ModelSpec
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/model-specs", tags=["model-specs"])

# context_window and max_output_tokens are INTEGER columns.
_INT32_MAX = 2**31 - 1
# The per-token costs are NUMERIC(20, 12): at most 8 integer digits.
_COST_CEILING = Decimal(10) ** 8


# Model Spec schemas
class ModelSpecCreate(BaseModel):
    provider_spec_id: UUID
    model_name: str
    display_name: str
    description: str | None = None
    context_window: int = Field(gt=0, le=_INT32_MAX)
    max_output_tokens: int | None = Field(default=None, gt=0, le=_INT32_MAX)
    input_cost_per_token: Money = Field(ge=ZERO, lt=_COST_CEILING)
    output_cost_per_token: Money = Field(ge=ZERO, lt=_COST_CEILING)
    default_context_strategy: str | None = None  # Auto-inferred from model_name if None
    is_active: bool = True


class ModelSpecUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    context_window: int | None = Field(default=None, gt=0, le=_INT32_MAX)
    max_output_tokens: int | None = Field(default=None, gt=0, le=_INT32_MAX)
    input_cost_per_token: Money | None = Field(default=None, ge=ZERO, lt=_COST_CEILING)
    output_cost_per_token: Money | None = Field(default=None, ge=ZERO, lt=_COST_CEILING)
    default_context_strategy: str | None = None
    is_active: bool | None = None


class ModelSpecResponse(BaseModel):
    id: str
    provider_spec_id: str
    model_name: str
    display_name: str
    description: str | None
    context_window: int
    max_output_tokens: int | None = None
    input_cost_per_token: Money | None = None
    output_cost_per_token: Money | None = None
    supports_function_calling: bool | None = False
    supports_vision: bool | None = False
    supports_reasoning: bool | None = False
    default_context_strategy: str | None
    is_active: bool
    created_at: UtcDatetime
    updated_at: UtcDatetime

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
@router.get(
    "/",
    response_model=list[ModelSpecResponse],
    dependencies=[unrestricted("platform catalogue data, identical for every workspace")],
)
async def list_model_specs(
    user_context: UserContextDep,
    provider_spec_id: UUID | None = None,
    is_active: bool | None = None,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """List model specifications with optional filtering."""
    model_specs = await model_spec_repo.list_specs(
        provider_spec_id=provider_spec_id,
        is_active=is_active,
    )
    return [ModelSpecResponse.from_domain(spec) for spec in model_specs]


@router.get(
    "/by-provider/{provider_spec_id}",
    response_model=list[ModelSpecResponse],
    dependencies=[unrestricted("platform catalogue data, identical for every workspace")],
)
async def list_model_specs_by_provider(
    provider_spec_id: UUID,
    user_context: UserContextDep,
    is_active: bool | None = None,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """List all model specifications for a specific provider."""
    model_specs = await model_spec_repo.list_specs(
        provider_spec_id=provider_spec_id,
        is_active=is_active,
    )
    return [ModelSpecResponse.from_domain(spec) for spec in model_specs]


@router.get(
    "/by-provider/{provider_spec_id}/{model_name}",
    response_model=ModelSpecResponse,
    dependencies=[unrestricted("platform catalogue data, identical for every workspace")],
)
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


@router.get(
    "/{model_spec_id}",
    response_model=ModelSpecResponse,
    dependencies=[unrestricted("platform catalogue data, identical for every workspace")],
)
async def get_model_spec(
    model_spec_id: UUID,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
):
    """Get a specific model specification by ID."""
    model_spec = await model_spec_repo.get_with_relations(model_spec_id)
    if not model_spec:
        raise HTTPException(status_code=404, detail="Model specification not found")
    return ModelSpecResponse.from_domain(model_spec)


@router.post(
    "/",
    response_model=ModelSpecResponse,
    dependencies=[requires_workspace_admin()],
)
async def create_model_spec(
    data: ModelSpecCreate,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
    model_spec_service: ModelSpecService = Depends(get_model_spec_service),
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
        created_spec = await model_spec_service.create(
            provider_spec_id=str(data.provider_spec_id),
            model_name=data.model_name,
            display_name=data.display_name,
            description=data.description,
            context_window=data.context_window,
            max_output_tokens=data.max_output_tokens,
            input_cost_per_token=data.input_cost_per_token,
            output_cost_per_token=data.output_cost_per_token,
            default_context_strategy=data.default_context_strategy,
            is_active=data.is_active,
        )
    except IntegrityError:
        # Concurrent insert raced past the pre-check and tripped the
        # uq_model_specs_workspace_provider_model unique constraint.
        raise HTTPException(
            status_code=409,
            detail=f"Model specification '{data.model_name}' already exists for this provider",
        ) from None
    created_spec = await model_spec_repo.get_with_relations(created_spec.id) or created_spec
    return ModelSpecResponse.from_domain(created_spec)


@router.patch(
    "/{model_spec_id}",
    response_model=ModelSpecResponse,
    dependencies=[requires_workspace_admin()],
)
async def update_model_spec(
    model_spec_id: UUID,
    data: ModelSpecUpdate,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
    model_spec_service: ModelSpecService = Depends(get_model_spec_service),
):
    """Update a model specification."""
    model_spec = await model_spec_repo.get_with_relations(model_spec_id)
    if not model_spec:
        raise HTTPException(status_code=404, detail="Model specification not found")

    updates = data.model_dump(exclude_none=True)
    updated_spec = await model_spec_service.update(model_spec_id, **updates)
    updated_spec = await model_spec_repo.get_with_relations(model_spec_id) or updated_spec
    if updated_spec is None:
        raise HTTPException(status_code=404, detail="Model specification not found")
    return ModelSpecResponse.from_domain(updated_spec)


@router.delete(
    "/{model_spec_id}",
    dependencies=[requires_workspace_admin()],
)
async def delete_model_spec(
    model_spec_id: UUID,
    user_context: UserContextDep,
    model_spec_service: ModelSpecService = Depends(get_model_spec_service),
):
    """Delete a model specification."""
    success = await model_spec_service.delete(model_spec_id)
    if not success:
        raise HTTPException(status_code=404, detail="Model specification not found")
    return {"message": "Model specification deleted successfully"}


@router.post(
    "/upsert",
    response_model=ModelSpecResponse,
    dependencies=[requires_workspace_admin()],
)
async def upsert_model_spec(
    data: ModelSpecCreate,
    user_context: UserContextDep,
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
    model_spec_service: ModelSpecService = Depends(get_model_spec_service),
):
    """Create or update a model specification by provider and model name.

    This endpoint is useful for bulk operations and bootstrapping.
    """
    upserted_spec = await model_spec_service.upsert(
        provider_spec_id=str(data.provider_spec_id),
        model_name=data.model_name,
        display_name=data.display_name,
        description=data.description,
        context_window=data.context_window,
        max_output_tokens=data.max_output_tokens,
        input_cost_per_token=data.input_cost_per_token,
        output_cost_per_token=data.output_cost_per_token,
        default_context_strategy=data.default_context_strategy,
        is_active=data.is_active,
    )
    upserted_spec = await model_spec_repo.get_with_relations(upserted_spec.id) or upserted_spec
    return ModelSpecResponse.from_domain(upserted_spec)
