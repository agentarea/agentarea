"""Execute one model request independently of workflow and progress transports."""

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, aclosing
from typing import Any, Protocol, cast
from uuid import UUID

from agentarea_agents_sdk import LLMModel, LLMRequest, LLMResponse
from agentarea_common.auth.context import UserContext
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.money import to_money
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_secrets.secret_manager_factory import SecretManagerFactory

from .exceptions import ModelInstanceNotFoundError
from .models import LLMCallRequest, LLMCallResult, LLMUsage

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


async def resolve_provider_api_key(
    *,
    reference: str | None,
    managed_by: str | None,
    user_context: UserContext,
    secret_manager_factory: SecretManagerFactory,
) -> str | None:
    """Read the credential this call runs on, from the workspace that owns it.

    ``reference`` is a secret name in both cases. What differs is whose secrets are
    searched, which is the whole reason this is one function and not a branch
    repeated at each call site:

      * tenant configuration (managed_by unset) — the caller's own workspace;
      * platform configuration — the platform workspace, which only the operator
        writes and which no tenant-scoped read can reach. The scoping that keeps
        tenants out of each other's secrets is what keeps them out of this one.

    Getting this branch wrong in either direction is silent: the name resolves to
    None in the wrong workspace and the provider answers 401, which reads as "the
    user's key is broken" — the one thing neither case is.
    """
    if not reference:
        return None

    from agentarea_common.config import get_database

    if managed_by == MANAGED_BY_PLATFORM:
        from agentarea_common.constants import PLATFORM_PRINCIPAL_ID, PLATFORM_WORKSPACE_ID

        secret_context = UserContext(
            user_id=PLATFORM_PRINCIPAL_ID,
            workspace_id=PLATFORM_WORKSPACE_ID,
        )
    else:
        secret_context = user_context

    secret_session = get_database().async_session_factory()
    try:
        secret_manager = secret_manager_factory.create(
            session=secret_session, user_context=secret_context
        )
        return await secret_manager.get_secret(reference)
    finally:
        await secret_session.close()


class LLMExecutionService:
    """Resolve and execute a single LLM call with mandatory usage accounting."""

    def __init__(
        self,
        *,
        model_service_scope: ModelServiceScope,
        secret_manager_factory: SecretManagerFactory,
        local_host: str,
        stream: bool = True,
    ) -> None:
        self._model_service_scope = model_service_scope
        self._secret_manager_factory = secret_manager_factory
        self._local_host = local_host
        self._stream = stream

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
            max_output_tokens = None
            input_cost_per_token = None
            output_cost_per_token = None

            if request.resolved_model:
                cached = request.resolved_model
                provider_type = cached.get("provider_type")
                model_name = cached.get("model_name")
                endpoint_url = cached.get("endpoint_url")
                max_output_tokens = cached.get("max_output_tokens")
                input_cost_per_token = cached.get("input_cost_per_token")
                output_cost_per_token = cached.get("output_cost_per_token")
                api_key_secret_name = cached.get("api_key_secret")
                if api_key_secret_name:
                    try:
                        api_key = await resolve_provider_api_key(
                            reference=api_key_secret_name,
                            managed_by=cached.get("managed_by"),
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
                    api_key_secret_name = getattr(model_instance.provider_config, "api_key", None)
                    if api_key_secret_name:
                        api_key = await resolve_provider_api_key(
                            reference=api_key_secret_name,
                            managed_by=getattr(model_instance.provider_config, "managed_by", None),
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
                input_cost_per_token=input_cost_per_token,
                output_cost_per_token=output_cost_per_token,
            )
            llm_request = LLMRequest(
                messages=request.messages,
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

            if self._stream:
                # The SDK yields from an async generator but annotates it as AsyncIterator.
                responses = cast(
                    AsyncGenerator[LLMResponse, None], llm_model.ainvoke_stream(llm_request)
                )
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

            if final_usage is None or getattr(final_usage, "total_tokens", 0) <= 0:
                raise RuntimeError(
                    "LLM usage accounting unavailable; token and cost policy cannot be enforced"
                )

            if self._stream and on_chunk is not None:
                await on_chunk("", chunk_index, True)

            return LLMCallResult(
                role="assistant",
                content="".join(content_parts),
                thinking="".join(thinking_parts),
                tool_calls=complete_tool_calls,
                cost=to_money(final_cost),
                usage=LLMUsage(
                    prompt_tokens=getattr(final_usage, "prompt_tokens", 0),
                    completion_tokens=getattr(final_usage, "completion_tokens", 0),
                    total_tokens=getattr(final_usage, "total_tokens", 0),
                ),
            )
        except Exception as error:
            if on_error is not None:
                try:
                    await on_error(error, provider_type)
                except Exception:
                    logger.exception("Failed to publish LLM execution error")
            raise
