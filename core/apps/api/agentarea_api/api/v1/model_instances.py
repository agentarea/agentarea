import logging
from datetime import datetime
from uuid import UUID

from agentarea_agents_sdk.models import LLMModel, LLMRequest

# Import LLM testing components
from agentarea_api.api.deps.services import get_provider_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.domain.models import ModelInstance
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

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


class ModelInstanceTestRequest(BaseModel):
    provider_config_id: UUID
    model_spec_id: UUID
    test_message: str | None = "Hello, this is a test message."


class ModelInstanceTestResponse(BaseModel):
    success: bool
    message: str
    response_content: str | None = None
    error_type: str | None = None
    provider_type: str | None = None
    model_name: str | None = None
    cost: float | None = None
    tokens_used: int | None = None


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


# Model Instance endpoints
@router.post("/", response_model=ModelInstanceResponse)
async def create_model_instance(
    data: ModelInstanceCreate,
    user_context: UserContextDep,
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
    user_context: UserContextDep,
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
    user_context: UserContextDep,
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
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Delete a model instance."""
    success = await provider_service.delete_model_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="Model instance not found")
    return {"message": "Model instance deleted successfully"}


@router.post("/test", response_model=ModelInstanceTestResponse)
async def validate_model_instance(
    data: ModelInstanceTestRequest,
    user_context: UserContextDep,
    provider_service: ProviderService = Depends(get_provider_service),
):
    """Test a model instance configuration before creating it."""
    try:
        # Get provider config and model spec
        provider_config = await provider_service.get_provider_config(data.provider_config_id)
        if not provider_config:
            raise HTTPException(status_code=404, detail="Provider config not found")

        model_spec = await provider_service.get_model_spec(data.model_spec_id)
        if not model_spec:
            raise HTTPException(status_code=404, detail="Model spec not found")

        # Extract configuration details
        provider_type = provider_config.provider_spec.provider_type
        model_name = model_spec.model_name
        endpoint_url = getattr(model_spec, "endpoint_url", None)

        # Get API key from secret manager
        api_key = None
        api_key_secret_name = getattr(provider_config, "api_key", None)
        if api_key_secret_name:
            # Get secret manager from provider service
            secret_manager = provider_service.secret_manager
            api_key = await secret_manager.get_secret(api_key_secret_name)

        if not api_key and provider_type not in ["ollama_chat"]:  # Ollama doesn't need API key
            return ModelInstanceTestResponse(
                success=False,
                message="No API key found for this provider configuration",
                error_type="MissingAPIKey",
                provider_type=provider_type,
                model_name=model_name,
            )

        # Prepare endpoint URL defaults
        resolved_endpoint_url = endpoint_url
        if not resolved_endpoint_url and provider_type == "ollama_chat":
            resolved_endpoint_url = "http://host.docker.internal:11434"

        logger.info(f"Testing LLM configuration via SDK: {provider_type}/{model_name}")

        # Use internal Agent SDK LLM model wrapper
        llm_model = LLMModel(
            provider_type=provider_type,
            model_name=model_name,
            api_key=api_key,
            endpoint_url=resolved_endpoint_url,
        )

        llm_request = LLMRequest(
            messages=[{"role": "user", "content": data.test_message}],
            max_tokens=50,
        )

        llm_response = await llm_model.complete(llm_request)

        tokens_used = llm_response.usage.total_tokens if llm_response.usage else 0

        return ModelInstanceTestResponse(
            success=True,
            message="LLM test successful",
            response_content=llm_response.content,
            provider_type=provider_type,
            model_name=model_name,
            cost=llm_response.cost,
            tokens_used=tokens_used,
        )

    except Exception as e:
        error_message = str(e)
        error_type = type(e).__name__

        logger.error(f"LLM test failed: {error_message}")

        # Categorize common errors
        if "AuthenticationError" in error_type or "api_key" in error_message.lower():
            error_type = "AuthenticationError"
            message = "Authentication failed - please check your API key"
        elif "RateLimitError" in error_type or "rate limit" in error_message.lower():
            error_type = "RateLimitError"
            message = "Rate limit exceeded - please try again later"
        elif "quota" in error_message.lower() or "billing" in error_message.lower():
            error_type = "QuotaError"
            message = "Quota exceeded or billing issue"
        elif "model" in error_message.lower() and (
            "not found" in error_message.lower() or "does not exist" in error_message.lower()
        ):
            error_type = "ModelNotFoundError"
            message = "Model not found or not available"
        elif "connection" in error_message.lower() or "timeout" in error_message.lower():
            error_type = "ConnectionError"
            message = "Connection failed - please check endpoint URL"
        else:
            message = f"Test failed: {error_message}"

        return ModelInstanceTestResponse(
            success=False,
            message=message,
            error_type=error_type,
            provider_type=provider_type if "provider_type" in locals() else None,
            model_name=model_name if "model_name" in locals() else None,
        )
