"""Execute one model request independently of workflow and progress transports."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, aclosing
from typing import Any, Protocol, cast
from uuid import UUID

import litellm
from agentarea_agents_sdk import LLMModel, LLMRequest, LLMResponse
from agentarea_common.auth.context import UserContext
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.extensions.customer_pricing import (
    CustomerPricing,
    get_customer_pricing,
    price_llm_call,
)
from agentarea_common.money import to_money, to_optional_money
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.application.provider_credentials import resolve_provider_api_key
from agentarea_secrets.secret_manager_factory import SecretManagerFactory

from .exceptions import ModelInstanceNotFoundError
from .models import LLMCallRequest, LLMCallResult, LLMUsage
from .tool_images import resolve_tool_images
from .workflows.context_store import ContextStore

logger = logging.getLogger(__name__)

ModelServiceScope = Callable[[UserContext], AbstractAsyncContextManager[ModelInstanceService]]
ErrorPublisher = Callable[[Exception, str | None], Awaitable[None]]


class ChunkPublisher(Protocol):
    async def __call__(
        self,
        chunk: str,
        chunk_index: int,
        is_final: bool = False,
        chunk_type: str = "text",
    ) -> None: ...


def resolve_llm_max_tokens(
    *,
    requested: int | None,
    model_cap: int | None,
    effective_policy: dict[str, Any] | None,
) -> int:
    """Resolve the strictest output-token ceiling with no runtime fallback."""
    policy_cap = ((effective_policy or {}).get("tokens") or {}).get("max_tokens_per_call")
    if not isinstance(policy_cap, int) or policy_cap <= 0:
        raise ValueError(
            "effective policy is missing required runtime limit tokens.max_tokens_per_call"
        )
    candidates = [policy_cap]
    for name, value in (("request.max_tokens", requested), ("model.max_output_tokens", model_cap)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        candidates.append(value)
    return min(candidates)


def model_reads_images(provider_type: str, model_name: str, spec_flag: bool | None) -> bool:
    """The model spec's word when it says yes; otherwise litellm's model map.

    Discovery leaves the spec flag unset for most models, so a ``False`` there
    is no evidence the model is blind.
    """
    if spec_flag:
        return True
    return bool(litellm.supports_vision(model=f"{provider_type}/{model_name}"))


async def _with_tool_images(
    request: LLMCallRequest, user_context: UserContext, *, vision: bool
) -> list[dict[str, Any]]:
    """The request's messages with the images tools returned attached."""
    if not any(message.get("attachments") for message in request.messages):
        return request.messages
    if not request.task_id:
        raise ValueError("tool images need the task they were stored under")
    store = ContextStore(str(user_context.workspace_id), str(request.task_id))
    return await resolve_tool_images(request.messages, read_image=store.read_image, vision=vision)


class LLMExecutionService:
    """Resolve and execute a single LLM call with mandatory usage accounting."""

    def __init__(
        self,
        *,
        model_service_scope: ModelServiceScope,
        secret_manager_factory: SecretManagerFactory,
        local_host: str,
        stream: bool = True,
        customer_pricing: CustomerPricing | None = None,
    ) -> None:
        self._model_service_scope = model_service_scope
        self._secret_manager_factory = secret_manager_factory
        self._local_host = local_host
        self._stream = stream
        # None = the process-wide pricing, looked up per call: this service is built
        # before the worker discovers extensions (see get_customer_pricing).
        self._customer_pricing = customer_pricing

    async def execute(
        self,
        request: LLMCallRequest,
        *,
        user_context: UserContext,
        on_chunk: ChunkPublisher | None = None,
        on_error: ErrorPublisher | None = None,
    ) -> LLMCallResult:
        """Return final accounting and optionally publish provisional stream deltas."""
        provider_type: str | None = None
        try:
            try:
                model_uuid = UUID(request.model_id)
            except ValueError as error:
                raise ValueError(
                    f"Invalid model_id: {request.model_id}. "
                    "Must be a valid UUID representing a model instance."
                ) from error

            model_name = None
            endpoint_url = None
            api_key = None
            managed_by: str | None = None
            max_output_tokens = None
            input_cost_per_token = None
            output_cost_per_token = None
            cached_input_cost_per_token = None

            supports_vision: bool | None = None
            if request.resolved_model:
                cached = request.resolved_model
                supports_vision = cached.get("supports_vision")
                provider_type = cached.get("provider_type")
                model_name = cached.get("model_name")
                endpoint_url = cached.get("endpoint_url")
                max_output_tokens = cached.get("max_output_tokens")
                input_cost_per_token = cached.get("input_cost_per_token")
                output_cost_per_token = cached.get("output_cost_per_token")
                cached_input_cost_per_token = cached.get("cached_input_cost_per_token")
                managed_by = cached.get("managed_by")
                api_key_secret_name = cached.get("api_key_secret")
                if api_key_secret_name:
                    try:
                        api_key = await resolve_provider_api_key(
                            reference=api_key_secret_name,
                            managed_by=managed_by,
                            user_context=user_context,
                            secret_manager_factory=self._secret_manager_factory,
                        )
                    except Exception as decrypt_error:
                        logger.warning(
                            f"Failed to decrypt cached API key for model {request.model_id}, "
                            f"falling back to DB lookup: {decrypt_error}",
                            exc_info=True,
                        )
                        provider_type = None

            if provider_type is None:
                async with self._model_service_scope(user_context) as model_service:
                    model_instance = await model_service.get(model_uuid)
                    if not model_instance:
                        raise ModelInstanceNotFoundError(
                            f"Model instance with ID {request.model_id} not found"
                        )
                    foreign = model_instance.foreign_part()
                    if foreign is not None:
                        raise ModelInstanceNotFoundError(
                            f"Model instance {request.model_id} uses a {foreign} "
                            "from another workspace"
                        )

                    provider_type = model_instance.provider_config.provider_spec.provider_type
                    model_name = model_instance.model_spec.model_name
                    endpoint_url = getattr(
                        model_instance.provider_config, "endpoint_url", None
                    ) or getattr(model_instance.model_spec, "endpoint_url", None)
                    max_output_tokens = getattr(
                        model_instance.model_spec, "max_output_tokens", None
                    )
                    input_cost_per_token = getattr(
                        model_instance.model_spec, "input_cost_per_token", None
                    )
                    output_cost_per_token = getattr(
                        model_instance.model_spec, "output_cost_per_token", None
                    )
                    cached_input_cost_per_token = getattr(
                        model_instance.model_spec, "cached_input_cost_per_token", None
                    )
                    managed_by = getattr(model_instance.provider_config, "managed_by", None)
                    supports_vision = getattr(model_instance.model_spec, "supports_vision", None)
                    api_key_secret_name = getattr(model_instance.provider_config, "api_key", None)
                    if api_key_secret_name:
                        api_key = await resolve_provider_api_key(
                            reference=api_key_secret_name,
                            managed_by=managed_by,
                            user_context=user_context,
                            secret_manager_factory=self._secret_manager_factory,
                        )
                    else:
                        logger.warning(f"No API key found for model instance {model_instance.id}")
                del model_instance, model_service

            if input_cost_per_token is None or output_cost_per_token is None:
                raise ValueError("model pricing is not configured; run budget cannot be enforced")

            if endpoint_url:
                endpoint_url = endpoint_url.replace("localhost", self._local_host).replace(
                    "127.0.0.1", self._local_host
                )

            llm_model = LLMModel(
                provider_type=str(provider_type),
                model_name=str(model_name),
                api_key=api_key,
                endpoint_url=endpoint_url,
                input_cost_per_token=to_optional_money(input_cost_per_token),
                output_cost_per_token=to_optional_money(output_cost_per_token),
                cached_input_cost_per_token=to_optional_money(cached_input_cost_per_token),
            )
            llm_request = LLMRequest(
                messages=await _with_tool_images(
                    request,
                    user_context,
                    vision=model_reads_images(str(provider_type), str(model_name), supports_vision),
                ),
                tools=request.tools,
                temperature=request.temperature,
                max_tokens=resolve_llm_max_tokens(
                    requested=request.max_tokens,
                    model_cap=max_output_tokens,
                    effective_policy=request.effective_policy,
                ),
            )

            content_parts: list[str] = []
            thinking_parts: list[str] = []
            complete_tool_calls = None
            final_usage = None
            final_cost = 0.0
            chunk_index = 0

            interrupted = False
            if self._stream:
                # The SDK yields from an async generator but annotates it as AsyncIterator.
                responses = cast(
                    AsyncGenerator[LLMResponse, None], llm_model.ainvoke_stream(llm_request)
                )
                try:
                    async with aclosing(responses):
                        async for response in responses:
                            if response.reasoning_content:
                                thinking_parts.append(response.reasoning_content)
                                if on_chunk is not None:
                                    await on_chunk(
                                        response.reasoning_content,
                                        chunk_index,
                                        False,
                                        chunk_type="thinking",
                                    )
                                    chunk_index += 1
                            if response.content:
                                content_parts.append(response.content)
                                if on_chunk is not None:
                                    await on_chunk(response.content, chunk_index, False)
                                    chunk_index += 1
                            # Tool calls are cumulative snapshots, not additional calls.
                            if response.tool_calls:
                                complete_tool_calls = response.tool_calls
                            if response.usage is not None:
                                final_usage = response.usage
                            if response.cost and response.cost > 0:
                                final_cost = max(final_cost, response.cost)
                except asyncio.CancelledError:
                    # Stopped mid-reply. Usage the provider already reported is
                    # what it bills; without it nothing is known, and the stop
                    # stands as a cancellation.
                    if final_usage is None or final_usage.total_tokens <= 0:
                        raise
                    interrupted = True
            else:
                response = await llm_model.complete(llm_request)
                if response.content:
                    content_parts.append(response.content)
                if response.reasoning_content:
                    thinking_parts.append(response.reasoning_content)
                if response.tool_calls:
                    complete_tool_calls = response.tool_calls
                final_usage = response.usage
                if response.cost and response.cost > 0:
                    final_cost = response.cost

            if final_usage is None or final_usage.total_tokens <= 0:
                raise RuntimeError(
                    "LLM usage accounting unavailable; token and cost policy cannot be enforced"
                )

            usage = LLMUsage(
                prompt_tokens=final_usage.prompt_tokens,
                completion_tokens=final_usage.completion_tokens,
                total_tokens=final_usage.total_tokens,
                cached_prompt_tokens=final_usage.cached_prompt_tokens,
                cache_creation_tokens=final_usage.cache_creation_tokens,
            )
            # Provider cost (USD) becomes what the customer pays, in the billing
            # currency. Events, task totals and budget enforcement all carry this
            # amount from here on, unconverted.
            provider_cost_usd = to_money(final_cost)
            cost = await price_llm_call(
                model_instance_id=str(model_uuid),
                platform_funded=managed_by == MANAGED_BY_PLATFORM,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                provider_cost_usd=provider_cost_usd,
                pricing=self._customer_pricing,
            )

            if self._stream and on_chunk is not None:
                await on_chunk("", chunk_index, True)

            return LLMCallResult(
                role="assistant",
                content="".join(content_parts),
                thinking="".join(thinking_parts),
                tool_calls=complete_tool_calls,
                cost=cost,
                provider_cost_usd=provider_cost_usd,
                # Resolved by price_llm_call just above, so this cannot fail to resolve.
                currency=(self._customer_pricing or get_customer_pricing()).currency(),
                managed_by=managed_by,
                usage=usage,
                interrupted=interrupted,
            )
        except Exception as error:
            if on_error is not None:
                try:
                    await on_error(error, provider_type)
                except Exception:
                    logger.exception("Failed to publish LLM execution error")
            raise
