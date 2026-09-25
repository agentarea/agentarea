"""Model resolution, model calls, context compaction and planning."""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_agents_sdk import GoalProgressEvaluator, LLMModel, LLMRequest
from agentarea_common.auth.context import UserContext
from agentarea_common.money import ZERO, to_money, to_optional_money
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ... import llm_execution_service
from ...exceptions import ModelInstanceNotFoundError
from ...interfaces import ActivityDependencies
from ...models import (
    CompactMessagesRequest,
    CompactMessagesResult,
    ExecutionPlanRequest,
    ExecutionPlanResult,
    GoalEvaluationRequest,
    GoalEvaluationResult,
    LLMCallRequest,
    LLMCallResult,
    LLMUsage,
    ResolvedModelInfo,
    ResolveModelRequest,
)
from ..event_publisher import create_event_publisher, publish_enriched_llm_error_event
from ..heartbeat import auto_heartbeater

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def make_llm_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @asynccontextmanager
    async def model_service_scope(user_context: UserContext):
        async with ActivityContext(container, user_context) as ctx:
            yield await ctx.get_model_instance_service()

    llm_service = llm_execution_service.LLMExecutionService(
        model_service_scope=model_service_scope,
        secret_manager_factory=dependencies.secret_manager_factory,
        local_host=dependencies.settings.app.local_host,
    )

    @activity.defn
    async def resolve_model_activity(
        request: ResolveModelRequest,
    ) -> dict:
        """Resolve model info once at workflow start and return as ResolvedModelInfo dict.

        This is called once during _initialize_agent_config and the result is cached
        in workflow state to avoid repeated DB lookups on every LLM call.
        """
        from datetime import UTC
        from uuid import UUID as _UUID

        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            model_instance_service = await ctx.get_model_instance_service()
            model_instance = await model_instance_service.get(_UUID(request.model_id))
            if not model_instance:
                raise ModelInstanceNotFoundError(f"Model instance {request.model_id} not found")
            foreign = model_instance.foreign_part()
            if foreign is not None:
                raise ModelInstanceNotFoundError(
                    f"Model instance {request.model_id} uses a {foreign} from another workspace"
                )

            provider_type = model_instance.provider_config.provider_spec.provider_type
            model_name = model_instance.model_spec.model_name
            # endpoint_url lives on provider_config (ollama, self-hosted, etc.), not model_spec.
            endpoint_url = getattr(model_instance.provider_config, "endpoint_url", None) or getattr(
                model_instance.model_spec, "endpoint_url", None
            )
            context_window = model_instance.model_spec.context_window
            if (
                isinstance(context_window, bool)
                or not isinstance(context_window, int)
                or context_window <= 0
            ):
                raise ValueError(f"ModelSpec for {request.model_id} has no valid context_window")
            max_output_tokens = getattr(model_instance.model_spec, "max_output_tokens", None)
            input_cost_per_token = getattr(model_instance.model_spec, "input_cost_per_token", None)
            output_cost_per_token = getattr(
                model_instance.model_spec, "output_cost_per_token", None
            )
            api_key_secret = getattr(model_instance.provider_config, "api_key", None)
            managed_by = getattr(model_instance.provider_config, "managed_by", None)
            display_name = getattr(model_instance.model_spec, "display_name", None)
            provider_display_name = getattr(
                model_instance.provider_config.provider_spec, "display_name", None
            )

        resolved = ResolvedModelInfo(
            model_id=request.model_id,
            provider_type=provider_type,
            model_name=model_name,
            api_key_secret=api_key_secret,
            managed_by=managed_by,
            endpoint_url=endpoint_url,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            input_cost_per_token=input_cost_per_token,
            output_cost_per_token=output_cost_per_token,
            display_name=display_name,
            provider_display_name=provider_display_name,
            resolved_at=datetime.now(UTC).isoformat(),
        )
        return resolved.model_dump()

    @activity.defn
    @auto_heartbeater
    async def call_llm_activity(
        request: LLMCallRequest,
    ) -> LLMCallResult:
        """Adapt one model call to Temporal and the task event transport."""

        async def on_error(error: Exception, provider_type: str | None) -> None:
            if request.task_id and request.agent_id and dependencies.event_broker:
                await publish_enriched_llm_error_event(
                    error=error,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    execution_id=request.execution_id or "",
                    model_id=request.model_id,
                    provider_type=provider_type,
                    event_broker=dependencies.event_broker,
                )

        try:
            try:
                if not request.workspace_id and not request.user_context_data:
                    raise ValueError("Either workspace_id or user_context_data must be provided")
                user_context = create_user_context(request.user_context_data)
            except Exception as error:
                try:
                    await on_error(error, None)
                except Exception:
                    logger.exception("Failed to publish LLM context error")
                raise

            on_chunk = None
            if request.task_id:
                on_chunk = create_event_publisher(
                    dependencies.event_broker,
                    request.task_id,
                    execution_id=request.execution_id,
                    iteration=request.iteration,
                    broker_client=dependencies.broker_client,
                )

            return await llm_service.execute(
                request,
                user_context=user_context,
                on_chunk=on_chunk,
                on_error=on_error,
            )
        except Exception as error:
            from ..event_publisher import _is_non_retryable_error

            error_message = str(error)
            logger.error(f"LLM call failed: {error_message}", exc_info=True)
            raise ApplicationError(
                f"LLM call failed: {error_message}",
                type=type(error).__name__,
                non_retryable=_is_non_retryable_error(error),
            ) from error

    @activity.defn
    @auto_heartbeater
    async def compact_messages_activity(
        request: CompactMessagesRequest,
    ) -> CompactMessagesResult:
        """Summarize older messages to reduce context window usage.

        Uses the same model as the agent to generate a concise summary
        of older conversation history, preserving key decisions, tool
        results, and reasoning.
        """
        try:
            model_uuid = UUID(request.model_id)

            if request.workspace_id:
                user_context = create_user_context(request.user_context_data)
            elif request.user_context_data:
                user_context = create_user_context(request.user_context_data)
            else:
                raise ValueError("Either workspace_id or user_context_data must be provided")

            # Dual path: use cached resolved_model if provided, else fall back to DB lookup
            provider_type = None
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
                        api_key = await llm_execution_service.resolve_provider_api_key(
                            reference=api_key_secret_name,
                            managed_by=cached.get("managed_by"),
                            user_context=user_context,
                            secret_manager_factory=dependencies.secret_manager_factory,
                        )
                    except Exception as decrypt_err:
                        logger.warning(
                            f"Failed to decrypt cached API key for model {request.model_id} "
                            f"in compact_messages, falling back to DB lookup: {decrypt_err}",
                            exc_info=True,
                        )
                        provider_type = None

            if provider_type is None:
                async with ActivityContext(container, user_context) as ctx:
                    model_instance_service = await ctx.get_model_instance_service()
                    model_instance = await model_instance_service.get(model_uuid)
                    if not model_instance:
                        raise ModelInstanceNotFoundError(
                            f"Model instance {request.model_id} not found"
                        )

                    provider_type = model_instance.provider_config.provider_spec.provider_type
                    model_name = model_instance.model_spec.model_name
                    # endpoint_url lives on provider_config (ollama, self-hosted, etc.), not model_spec.
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
                        api_key = await llm_execution_service.resolve_provider_api_key(
                            reference=api_key_secret_name,
                            managed_by=getattr(model_instance.provider_config, "managed_by", None),
                            user_context=user_context,
                            secret_manager_factory=dependencies.secret_manager_factory,
                        )

            if input_cost_per_token is None or output_cost_per_token is None:
                raise ValueError(
                    "model pricing is not configured; compaction budget cannot be enforced"
                )

            if endpoint_url:
                local_host = dependencies.settings.app.local_host
                endpoint_url = endpoint_url.replace("localhost", local_host).replace(
                    "127.0.0.1", local_host
                )

            llm_model = LLMModel(
                provider_type=provider_type,
                model_name=str(model_name),
                api_key=api_key,
                endpoint_url=endpoint_url,
                input_cost_per_token=to_optional_money(input_cost_per_token),
                output_cost_per_token=to_optional_money(output_cost_per_token),
            )

            # Build compaction prompt
            conversation_text = ""
            for msg in request.messages_to_compact:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if msg.get("tool_calls"):
                    tool_names = [
                        tc.get("function", {}).get("name", "?")
                        for tc in msg["tool_calls"]
                        if isinstance(tc, dict)
                    ]
                    content += f" [Called tools: {', '.join(tool_names)}]"
                if msg.get("name"):
                    role = f"tool({msg['name']})"
                conversation_text += f"[{role}]: {content}\n"

            compaction_prompt = (
                "Summarize the following conversation history concisely. Preserve:\n"
                "1. The original task/goal\n"
                "2. Key decisions made and reasoning\n"
                "3. Important tool results and data obtained\n"
                "4. Current state of progress\n"
                "5. Any errors encountered and how they were handled\n\n"
                "Be concise but complete. Use bullet points for key facts.\n\n"
                f"Conversation to summarize:\n{conversation_text}"
            )

            summary_request = LLMRequest(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a conversation summarizer. Create concise, factual "
                            "summaries that preserve all important information for "
                            "continuing the task."
                        ),
                    },
                    {"role": "user", "content": compaction_prompt},
                ],
                max_tokens=llm_execution_service.resolve_llm_max_tokens(
                    requested=None,
                    model_cap=max_output_tokens,
                    effective_policy=request.effective_policy,
                ),
            )

            complete_content = ""
            final_usage = None
            final_cost = ZERO
            async for chunk in llm_model.ainvoke_stream(summary_request):
                if chunk.content:
                    complete_content += chunk.content
                if chunk.usage is not None:
                    final_usage = chunk.usage
                if chunk.cost and chunk.cost > final_cost:
                    final_cost = to_money(chunk.cost)

            if final_usage is None or final_usage.total_tokens <= 0:
                raise RuntimeError(
                    "compaction usage accounting unavailable; budget cannot be enforced"
                )

            original_tokens = sum(
                len(msg.get("content", "") or "") // 4 for msg in request.messages_to_compact
            )
            summary_tokens = len(complete_content) // 4

            return CompactMessagesResult(
                summary=complete_content,
                original_message_count=len(request.messages_to_compact),
                estimated_tokens_saved=max(0, original_tokens - summary_tokens),
                cost=final_cost,
                usage=LLMUsage(
                    prompt_tokens=final_usage.prompt_tokens,
                    completion_tokens=final_usage.completion_tokens,
                    total_tokens=final_usage.total_tokens,
                ),
            )

        except Exception as e:
            logger.error(f"Message compaction failed: {e}", exc_info=True)
            from temporalio.exceptions import ApplicationError

            from ..event_publisher import _is_non_retryable_error

            raise ApplicationError(
                f"Message compaction failed: {e}",
                type=type(e).__name__,
                non_retryable=_is_non_retryable_error(e),
            ) from e

    @activity.defn
    async def create_execution_plan_activity(
        request: ExecutionPlanRequest,
    ) -> ExecutionPlanResult:
        """Create an execution plan based on the goal and available tools."""
        try:
            # For now, return a simple plan - could be enhanced with actual LLM call
            tool_names = [tool.get("name", "unknown") for tool in request.available_tools]

            return ExecutionPlanResult(
                plan=(
                    f"Execute the task '{request.goal.get('description', 'Unknown')}' "
                    "systematically using available tools"
                ),
                estimated_steps=min(max(len(request.available_tools), 3), 8),  # Between 3-8 steps
                key_tools=tool_names[:3],  # First 3 tools
                risk_factors=[
                    "Tool execution failures",
                    "LLM response issues",
                    "External API timeouts",
                ],
            )

        except Exception as e:
            logger.error(f"Failed to create execution plan: {e}", exc_info=True)
            return ExecutionPlanResult(
                plan=(
                    f"Execute the task '{request.goal.get('description', 'Unknown')}' step by step"
                ),
                estimated_steps=5,
                key_tools=[],
                risk_factors=["Planning failed - proceeding with default approach"],
            )

    @activity.defn
    async def evaluate_goal_progress_activity(
        request: GoalEvaluationRequest,
    ) -> GoalEvaluationResult:
        """Evaluate progress toward the goal."""
        evaluator = GoalProgressEvaluator()

        # Extract goal information for the new interface
        goal_description = request.goal.get("description", "")
        success_criteria = request.goal.get("success_criteria", [])

        evaluation = await evaluator.evaluate_progress(
            goal_description=goal_description,
            success_criteria=success_criteria,
            conversation_history=request.messages,
            current_iteration=request.current_iteration,
        )

        return GoalEvaluationResult(
            goal_achieved=evaluation.get("goal_achieved", False),
            confidence=evaluation.get("confidence", 0.0),
            final_response=evaluation.get("final_response"),
            reasoning=evaluation.get("reasoning", ""),
            next_steps=evaluation.get("next_steps", []),
        )

    return [
        resolve_model_activity,
        call_llm_activity,
        compact_messages_activity,
        create_execution_plan_activity,
        evaluate_goal_progress_activity,
    ]
