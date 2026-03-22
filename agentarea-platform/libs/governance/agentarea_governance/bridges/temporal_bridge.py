"""Temporal bridge — adapts the interceptor pipeline to Temporal's ActivityInboundInterceptor.

This is the ONLY module in the governance library that imports temporalio.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from agentarea_execution.workflows.constants import Activities
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
    WorkflowInboundInterceptor,
)

from ..domain.enums import InterceptorAction, Phase
from ..domain.exceptions import EscalationRequired, GovernanceDenied
from ..domain.models import InterceptorContext
from ..pipeline import InterceptorPipeline

logger = logging.getLogger(__name__)

# Activity name → (pre_phase, post_phase) mapping
# References Activities constants to stay in sync with activity definitions
_ACTIVITY_PHASE_MAP: dict[str, tuple[Phase | None, Phase | None]] = {
    Activities.CALL_LLM: (Phase.PRE_LLM_CALL, Phase.POST_LLM_CALL),
    Activities.EXECUTE_MCP_TOOL: (Phase.PRE_TOOL_CALL, Phase.POST_TOOL_CALL),
    Activities.DISCOVER_AVAILABLE_TOOLS: (None, Phase.TOOL_DISCOVERY),
}


def _extract_context_from_input(
    activity_input: ExecuteActivityInput,
    phase: Phase,
) -> InterceptorContext | None:
    """Build InterceptorContext from the activity's request argument."""
    args = activity_input.args
    if not args:
        return None

    request = args[0]
    if not hasattr(request, "__dict__"):
        return None

    # Extract fields from request models (LLMCallRequest, MCPToolRequest, etc.)
    agent_id = _extract_uuid(request, "agent_id")
    workspace_id = _extract_str(request, "workspace_id")
    user_id = _extract_user_id(request)
    action_name = _extract_action_name(request, activity_input.fn.__name__)
    action_type = _resolve_action_type(activity_input.fn.__name__)

    if not workspace_id:
        # Try user_context_data as fallback
        ucd = getattr(request, "user_context_data", None) or {}
        workspace_id = ucd.get("workspace_id", "")
        if not agent_id:
            agent_id = _extract_uuid_from_str(ucd.get("user_id"))

    return InterceptorContext(
        agent_id=agent_id or UUID(int=0),
        workspace_id=workspace_id or "",
        user_id=user_id,
        phase=phase,
        action_type=action_type,
        action_name=action_name,
        action_params=_extract_params(request),
    )


def _extract_uuid(obj: Any, field: str) -> UUID | None:
    val = getattr(obj, field, None)
    if isinstance(val, UUID):
        return val
    if isinstance(val, str):
        return _extract_uuid_from_str(val)
    return None


def _extract_uuid_from_str(val: Any) -> UUID | None:
    if not val:
        return None
    try:
        return UUID(str(val))
    except (ValueError, AttributeError):
        return None


def _extract_str(obj: Any, field: str) -> str:
    val = getattr(obj, field, None)
    return str(val) if val else ""


def _extract_user_id(request: Any) -> str:
    if hasattr(request, "user_id"):
        return str(request.user_id)
    ucd = getattr(request, "user_context_data", None) or {}
    return ucd.get("user_id", "")


def _extract_action_name(request: Any, activity_name: str) -> str:
    # LLMCallRequest → model_id
    if hasattr(request, "model_id"):
        return str(request.model_id)
    # MCPToolRequest → tool_name
    if hasattr(request, "tool_name"):
        return str(request.tool_name)
    return activity_name


def _resolve_action_type(activity_name: str) -> str:
    if "llm" in activity_name:
        return "llm_call"
    if "mcp_tool" in activity_name:
        return "tool_call"
    if "discover" in activity_name:
        return "tool_discovery"
    if "delegation" in activity_name:
        return "agent_delegation"
    return activity_name


def _extract_params(request: Any) -> dict[str, Any]:
    if hasattr(request, "tool_args"):
        return dict(request.tool_args)
    if hasattr(request, "model_dump"):
        try:
            return request.model_dump()
        except Exception:  # noqa: S110
            pass
    return {}


class GovernanceActivityInterceptor(ActivityInboundInterceptor):
    """Wraps activity execution with the interceptor pipeline."""

    def __init__(
        self,
        next: ActivityInboundInterceptor,
        pipeline: InterceptorPipeline,
    ) -> None:
        super().__init__(next)
        self._pipeline = pipeline

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        activity_name = input.fn.__name__
        phases = _ACTIVITY_PHASE_MAP.get(activity_name)

        if not phases:
            return await self.next.execute_activity(input)

        pre_phase, post_phase = phases

        # Run pre-phase interceptors
        if pre_phase and self._pipeline._registry.has_interceptors(pre_phase):
            context = _extract_context_from_input(input, pre_phase)
            if context:
                result = await self._pipeline.run(pre_phase, context)
                if result.action == InterceptorAction.DENY:
                    raise GovernanceDenied(
                        reason=result.reason,
                        interceptor_name=result.interceptor_name,
                        metadata=result.metadata,
                    )
                if result.action == InterceptorAction.ESCALATE:
                    raise EscalationRequired(
                        reason=result.reason,
                        interceptor_name=result.interceptor_name,
                        metadata=result.metadata,
                    )

        # Execute the actual activity
        output = await self.next.execute_activity(input)

        # Run post-phase interceptors
        if post_phase and self._pipeline._registry.has_interceptors(post_phase):
            context = _extract_context_from_input(input, post_phase)
            if context:
                # For post-phases, attach output content if available
                content = _extract_content_from_output(output)
                if content is not None:
                    context = InterceptorContext(
                        agent_id=context.agent_id,
                        workspace_id=context.workspace_id,
                        user_id=context.user_id,
                        phase=post_phase,
                        action_type=context.action_type,
                        action_name=context.action_name,
                        action_params=context.action_params,
                        content=content,
                        execution_state=context.execution_state,
                    )
                result = await self._pipeline.run(post_phase, context)
                if (
                    result.action == InterceptorAction.MODIFY
                    and result.modified_content is not None
                ):
                    output = _apply_modification(output, result.modified_content)
                if result.action == InterceptorAction.DENY:
                    raise GovernanceDenied(
                        reason=result.reason,
                        interceptor_name=result.interceptor_name,
                    )

        return output


def _extract_content_from_output(output: Any) -> str | None:
    """Extract text content from activity output for filter processing."""
    if isinstance(output, str):
        return output
    # LLMCallResult has content field
    if hasattr(output, "content"):
        return str(output.content) if output.content else None
    # MCPToolResult has result field
    if hasattr(output, "result"):
        return str(output.result) if output.result else None
    return None


def _apply_modification(output: Any, modified_content: str) -> Any:
    """Apply filtered content back to the activity output."""
    if isinstance(output, str):
        return modified_content
    if hasattr(output, "content"):
        output.content = modified_content
    elif hasattr(output, "result"):
        output.result = modified_content
    return output


class GovernanceWorkerInterceptor(Interceptor):
    """Top-level Temporal worker interceptor that creates the activity interceptor."""

    def __init__(self, pipeline: InterceptorPipeline) -> None:
        self._pipeline = pipeline

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return GovernanceActivityInterceptor(next, self._pipeline)

    def workflow_interceptor_class(self, input: Any) -> type[WorkflowInboundInterceptor] | None:
        return None


def validate_activity_mapping(registered_activities: list[str]) -> None:
    """Validate that all mapped activity names exist in the worker's activities."""
    for activity_name in _ACTIVITY_PHASE_MAP:
        if activity_name not in registered_activities:
            logger.warning(
                "Governance bridge maps activity '%s' but it is not registered on this worker",
                activity_name,
            )
