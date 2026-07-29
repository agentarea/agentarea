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
    instance.budget_tracker = BudgetTracker(None)
    return instance


def _completion(call_id: str = "completion-1") -> ToolCall:
    return ToolCall(
        id=call_id,
        function={
            "name": "completion",
            "arguments": json.dumps(
                {"result": "done", "artifact_paths": ["reports/q3.xlsx"]}
            ),
        },
    )


@pytest.mark.asyncio
async def test_completion_updates_task_only_after_validation_passes() -> None:
    instance = _workflow()
    instance._validate_completion_artifacts = AsyncMock(
        return_value=ArtifactValidationResult(state="passed", generation=4)
    )

    with patch(
        "agentarea_execution.workflows.agent_execution_workflow.workflow.execute_activity",
        new=AsyncMock(),
    ) as execute_activity, patch(
        "agentarea_execution.workflows.agent_execution_workflow.workflow.logger",
        new=Mock(),
    ):
        await instance._handle_task_completion(_completion())

    instance._validate_completion_artifacts.assert_awaited_once_with(["reports/q3.xlsx"])
    assert instance.state.success is True
    assert instance.state.final_response == "done"
    assert instance._awaiting_input is True
    assert execute_activity.await_count == 1
    request = execute_activity.await_args.kwargs["args"][0]
    assert request.status == "completed"


@pytest.mark.asyncio
async def test_failed_validation_returns_tool_feedback_for_two_repairs() -> None:
    instance = _workflow()
    completion = _completion()
    instance.state.messages.append(
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {"id": completion.id, "type": "function", "function": completion.function}
            ],
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

    with patch(
        "agentarea_execution.workflows.agent_execution_workflow.workflow.execute_activity",
        new=AsyncMock(return_value=ArtifactValidationResult(state="passed", generation=9)),
    ), patch(
        "agentarea_execution.workflows.helpers.workflow.logger",
        new=Mock(),
    ):
        result = await instance._validate_completion_artifacts(["reports/q3.xlsx"])

    assert result.state == "passed"
    event_types = [event["event_type"] for event in instance._events.get_pending_events()]
    assert event_types == ["artifact.validation.started", "artifact.validation.completed"]
    assert "task.completed" not in event_types
