"""Tests for workflow error sanitization.

Verifies that when activities fail, the workflow publishes user-friendly
error messages via WorkflowFailed events — never raw stack traces or
internal Temporal/Pydantic details.

Uses Temporal's WorkflowEnvironment with mock activities so the full
error path is exercised: activity raises → workflow catches →
_handle_workflow_error → publish_workflow_events_activity called with
sanitized payload.
"""

import concurrent.futures
import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    LLMCallRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    ToolDiscoveryResult,
    WorkflowEventsRequest,
)
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


# ── Forbidden fragments that must never appear in user-facing error events ──

FORBIDDEN_FRAGMENTS = [
    "Traceback",
    'File "/',
    "ActivityError",
    "ApplicationError",
    "input_value=None",
    "retry_state=",
    "cause=",
    "activity task failed",
    "scheduled_event_id",
]


# ── Shared mock activities ──────────────────────────────────────────────────


def _base_activities(
    *,
    build_agent_config_fn=None,
    call_llm_fn=None,
):
    """Return a list of mock activity definitions.

    Override specific activities by passing callables.
    """

    # ── build_agent_config ──
    if build_agent_config_fn is None:

        @activity.defn(name="build_agent_config_activity")
        async def build_agent_config_activity(
            request: AgentConfigRequest,
        ) -> dict[str, Any]:
            return {
                "id": str(request.agent_id),
                "name": "Test Agent",
                "model_id": "gpt-4",
                "instruction": "You are a helpful assistant.",
                "tools_config": {"mcp_servers": []},
                "events_config": {},
                "planning": False,
            }
    else:
        build_agent_config_activity = build_agent_config_fn

    # ── discover tools ──
    @activity.defn(name="discover_available_tools_activity")
    async def discover_available_tools_activity(
        request: ToolDiscoveryRequest,
    ) -> ToolDiscoveryResult:
        return ToolDiscoveryResult(tools=[])

    # ── resolve model ──
    @activity.defn(name="resolve_model_activity")
    async def resolve_model_activity(request: ResolveModelRequest) -> dict[str, Any]:
        return {
            "model_id": request.model_id,
            "provider_type": "openai",
            "model_name": "gpt-4",
            "api_key_secret": None,
            "endpoint_url": None,
            "context_window": 128000,
            "display_name": "GPT-4",
            "provider_display_name": "OpenAI",
            "resolved_at": "2026-01-01T00:00:00+00:00",
        }

    # ── call_llm ──
    if call_llm_fn is None:

        @activity.defn(name="call_llm_activity")
        async def call_llm_activity(
            request: LLMCallRequest,
        ) -> dict[str, Any]:
            return {
                "content": "Done.",
                "role": "assistant",
                "tool_calls": [],
                "finish_reason": "stop",
                "cost": 0.001,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
    else:
        call_llm_activity = call_llm_fn

    @activity.defn(name="execute_mcp_tool_activity")
    async def execute_mcp_tool_activity(
        tool_name: str,
        tool_args: dict[str, Any],
        server_instance_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        return {"success": True, "result": "mock", "tool_name": tool_name}

    @activity.defn(name="evaluate_goal_progress_activity")
    async def evaluate_goal_progress_activity(
        goal: dict[str, Any],
        messages: list[dict[str, Any]],
        current_iteration: int,
    ) -> dict[str, Any]:
        return {
            "goal_achieved": True,
            "final_response": "Done",
            "success_criteria_met": [],
            "progress_indicators": {},
        }

    @activity.defn(name="update_task_status_activity")
    async def update_task_status_activity(*args: Any, **kwargs: Any) -> bool:
        return True

    # The publish activity is created by the caller so it can capture events.
    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        resolve_model_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        evaluate_goal_progress_activity,
        update_task_status_activity,
    ]


def _make_request(**overrides) -> AgentExecutionRequest:
    defaults = dict(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test_user",
        workspace_id="test-workspace",
        task_query="Hello",
        timeout_seconds=30,
        max_reasoning_iterations=3,
    )
    defaults.update(overrides)
    return AgentExecutionRequest(**defaults)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _extract_error_from_published_events(captured: list[list[str]]) -> str | None:
    """Find the failure event payload and return its 'error' field.

    The emit-side canonicalizes ``WorkflowFailed`` to ``task.failed``.
    """
    for batch in captured:
        for event_json in batch:
            event = json.loads(event_json)
            if event.get("event_type") == "task.failed":
                return event["data"]["error"]
    return None


def _assert_no_forbidden_fragments(error_message: str) -> None:
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in error_message, (
            f"Forbidden fragment '{fragment}' found in user-facing error: {error_message}"
        )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestWorkflowErrorSanitization:
    """Verify that workflow failures publish sanitized error events."""

    @pytest.mark.asyncio
    async def test_missing_model_publishes_config_error(self):
        """When build_agent_config fails with missing model_id,
        the published error must mention model/settings, not Pydantic details."""
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            captured_events: list[list[str]] = []

            @activity.defn(name="build_agent_config_activity")
            async def failing_build(
                request: AgentConfigRequest,
            ) -> dict[str, Any]:
                raise ValueError(
                    "model_id\n  Input should be a valid string [type=string_type, "
                    "input_value=None, input_type=NoneType]"
                )

            @activity.defn(name="publish_workflow_events_activity")
            async def capture_events(request: WorkflowEventsRequest) -> bool:
                captured_events.append(request.events_json)
                return True

            activities = _base_activities(build_agent_config_fn=failing_build)
            activities.append(capture_events)

            task_queue = str(uuid.uuid4())
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[AgentExecutionWorkflow],
                    activities=activities,
                    activity_executor=executor,
                )
                async with worker:
                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        _make_request(),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                        execution_timeout=timedelta(minutes=1),
                    )
                    with pytest.raises(Exception):
                        await handle.result()

            error_msg = _extract_error_from_published_events(captured_events)
            assert error_msg is not None, "No WorkflowFailed event published"
            assert "model" in error_msg.lower()
            assert "settings" in error_msg.lower()
            _assert_no_forbidden_fragments(error_msg)

    @pytest.mark.asyncio
    async def test_llm_auth_failure_publishes_auth_error(self):
        """When call_llm fails with auth error, user sees 'authentication' not stack trace."""
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            captured_events: list[list[str]] = []

            @activity.defn(name="call_llm_activity")
            async def failing_llm(
                request: LLMCallRequest,
            ) -> dict[str, Any]:
                raise RuntimeError("call_llm: Unauthorized - invalid api_key for provider openai")

            @activity.defn(name="publish_workflow_events_activity")
            async def capture_events(request: WorkflowEventsRequest) -> bool:
                captured_events.append(request.events_json)
                return True

            activities = _base_activities(call_llm_fn=failing_llm)
            activities.append(capture_events)

            task_queue = str(uuid.uuid4())
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[AgentExecutionWorkflow],
                    activities=activities,
                    activity_executor=executor,
                )
                async with worker:
                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        _make_request(),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                        execution_timeout=timedelta(minutes=1),
                    )
                    with pytest.raises(Exception):
                        await handle.result()

            error_msg = _extract_error_from_published_events(captured_events)
            assert error_msg is not None, "No WorkflowFailed event published"
            assert "authentication" in error_msg.lower() or "api key" in error_msg.lower()
            _assert_no_forbidden_fragments(error_msg)

    @pytest.mark.asyncio
    async def test_generic_activity_failure_hides_internals(self):
        """Any activity failure must produce a clean message with no Temporal internals."""
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            captured_events: list[list[str]] = []

            @activity.defn(name="build_agent_config_activity")
            async def failing_build(
                request: AgentConfigRequest,
            ) -> dict[str, Any]:
                raise RuntimeError(
                    "Traceback (most recent call last):\n"
                    '  File "/app/worker.py", line 42, in execute\n'
                    "    raise ValueError('connection refused')\n"
                    "ValueError: connection refused"
                )

            @activity.defn(name="publish_workflow_events_activity")
            async def capture_events(request: WorkflowEventsRequest) -> bool:
                captured_events.append(request.events_json)
                return True

            activities = _base_activities(build_agent_config_fn=failing_build)
            activities.append(capture_events)

            task_queue = str(uuid.uuid4())
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[AgentExecutionWorkflow],
                    activities=activities,
                    activity_executor=executor,
                )
                async with worker:
                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        _make_request(),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                        execution_timeout=timedelta(minutes=1),
                    )
                    with pytest.raises(Exception):
                        await handle.result()

            error_msg = _extract_error_from_published_events(captured_events)
            assert error_msg is not None, "No WorkflowFailed event published"
            _assert_no_forbidden_fragments(error_msg)
            # Should be a short, actionable sentence
            assert len(error_msg) < 200, f"Error message too long ({len(error_msg)} chars): {error_msg}"
