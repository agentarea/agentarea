import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentarea_execution.models import (
    ArtifactValidationIssue,
    ArtifactValidationResult,
)
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import BudgetTracker, EventManager
from agentarea_execution.workflows.models import Message, ToolCall


def _workflow() -> AgentExecutionWorkflow:
    instance = AgentExecutionWorkflow()
    instance.state.workspace_id = "workspace-1"
    instance.state.task_id = "task-1"
    instance.state.execution_id = "workflow-1"
    instance.state.user_id = "user-1"
    instance.state.agent_id = "agent-1"
    instance.event_manager = EventManager(
        task_id="task-1", agent_id="agent-1", execution_id="workflow-1"
    )
    instance.budget_tracker = BudgetTracker(1)
    return instance


def _completion(call_id: str = "completion-1") -> ToolCall:
    return ToolCall(
        id=call_id,
        function={
            "name": "completion",
            "arguments": json.dumps(
                {
                    "result": "done",
                    "artifacts": ["reports/model.xlsx"],
                }
            ),
        },
    )


def _completion_with(arguments: dict | str, call_id: str = "completion-1") -> ToolCall:
    return ToolCall(
        id=call_id,
        function={
            "name": "completion",
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
    )


@pytest.mark.asyncio
async def test_completion_updates_task_only_after_validation_passes() -> None:
    instance = _workflow()
    instance._publish_events_immediately = AsyncMock()
    instance._validate_completion_artifacts = AsyncMock(
        return_value=ArtifactValidationResult(state="passed", generation=4)
    )

    with (
        patch(
            "agentarea_execution.workflows.agent_execution_workflow.workflow.execute_activity",
            new=AsyncMock(),
        ) as execute_activity,
        patch(
            "agentarea_execution.workflows.agent_execution_workflow.workflow.logger",
            new=Mock(),
        ),
    ):
        await instance._handle_task_completion(_completion())

    instance._validate_completion_artifacts.assert_awaited_once_with(["reports/model.xlsx"])
    assert instance.state.success is True
    assert instance.state.final_response == "done"
    assert instance._awaiting_input is True
    assert execute_activity.await_count == 1
    request = execute_activity.await_args.kwargs["args"][0]
    assert request.status == "completed"
    pending_events = instance._events.get_pending_events()
    assert pending_events[-1]["event_type"] == "task.awaiting_follow_up"
    assert pending_events[-1]["data"]["state"] == "awaiting_follow_up"
    assert pending_events[-1]["data"]["timeout_seconds"] == 1800


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        ({"result": "done"}, "artifacts is required"),
        ({"result": "done", "artifacts": "reports/model.xlsx"}, "must be an array"),
        ({"result": "done", "artifacts": [1]}, "non-empty workspace-relative paths"),
        ("not-json", "valid JSON"),
    ],
)
async def test_invalid_completion_arguments_are_rejected_without_defaults(
    arguments: dict | str, expected_error: str
) -> None:
    instance = _workflow()
    instance._validate_completion_artifacts = AsyncMock()

    await instance._handle_task_completion(_completion_with(arguments))

    instance._validate_completion_artifacts.assert_not_awaited()
    assert instance.state.success is False
    assert instance.state.final_response is None
    feedback = json.loads(instance.state.messages[-1].content)
    assert feedback["status"] == "invalid_completion_arguments"
    assert expected_error in feedback["error"]


@pytest.mark.asyncio
async def test_explicit_empty_artifacts_is_a_valid_completion_contract() -> None:
    instance = _workflow()
    instance._validate_completion_artifacts = AsyncMock(
        return_value=ArtifactValidationResult(state="passed", generation=1)
    )

    with (
        patch(
            "agentarea_execution.workflows.agent_execution_workflow.workflow.execute_activity",
            new=AsyncMock(),
        ),
        patch(
            "agentarea_execution.workflows.agent_execution_workflow.workflow.logger",
            new=Mock(),
        ),
    ):
        await instance._handle_task_completion(
            _completion_with({"result": "done", "artifacts": []})
        )

    instance._validate_completion_artifacts.assert_awaited_once_with([])


@pytest.mark.asyncio
async def test_failed_validation_returns_tool_feedback_for_two_repairs() -> None:
    instance = _workflow()
    completion = _completion()
    instance.state.messages.append(
        Message(
            role="assistant",
            content="",
            tool_calls=[{"id": completion.id, "type": "function", "function": completion.function}],
        )
    )
    failure = ArtifactValidationResult(
        state="failed",
        generation=4,
        issues=[
            ArtifactValidationIssue(
                path="reports/q3.xlsx",
                validator="openpyxl",
                code="validation_failed",
                message="invalid workbook",
            )
        ],
    )
    instance._validate_completion_artifacts = AsyncMock(return_value=failure)

    await instance._handle_task_completion(completion)
    assert instance.state.validation_repair_attempts == 1
    assert instance.state.success is False
    feedback = json.loads(instance.state.messages[-1].content)
    assert feedback["status"] == "validation_failed"
    assert feedback["repair_attempts_remaining"] == 1
    assert "completion again with the workspace-relative paths" in feedback["instruction"]
    assert "artifact_id" not in feedback["instruction"]
    assert instance.state.messages[-1].tool_call_id == completion.id

    await instance._handle_task_completion(completion)
    assert instance.state.validation_repair_attempts == 2
    assert instance.state.validation_terminal is False

    await instance._handle_task_completion(completion)
    assert instance.state.validation_terminal is True
    assert instance.state.failure_reason == "validation_failed"


@pytest.mark.asyncio
async def test_unavailable_validator_blocks_without_completion_transition() -> None:
    from agentarea_execution.models import CapabilityUnavailableResult

    instance = _workflow()
    instance._validate_completion_artifacts = AsyncMock(
        return_value=ArtifactValidationResult(
            state="unavailable",
            generation=2,
            capability_unavailable=CapabilityUnavailableResult(capability="browser"),
        )
    )

    with patch(
        "agentarea_execution.workflows.agent_execution_workflow.workflow.execute_activity",
        new=AsyncMock(),
    ) as execute_activity:
        await instance._handle_task_completion(_completion())

    assert execute_activity.await_count == 0
    assert instance.state.status == "blocked"
    assert instance.state.failure_reason == "capability_unavailable"
    assert instance.state.validation_terminal is True


@pytest.mark.asyncio
async def test_validation_audit_events_precede_any_terminal_event() -> None:
    instance = _workflow()
    instance._publish_events_immediately = AsyncMock()

    with (
        patch(
            "agentarea_execution.workflows.agent_execution_workflow.workflow.execute_activity",
            new=AsyncMock(return_value=ArtifactValidationResult(state="passed", generation=9)),
        ),
        patch(
            "agentarea_execution.workflows.helpers.workflow.logger",
            new=Mock(),
        ),
    ):
        result = await instance._validate_completion_artifacts(
            ["art_0123456789abcdef0123456789abcdef"]
        )

    assert result.state == "passed"
    event_types = [event["event_type"] for event in instance._events.get_pending_events()]
    assert event_types == ["artifact.validation.started", "artifact.validation.completed"]
    assert "task.completed" not in event_types
