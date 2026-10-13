"""recall_history reads its activity's result as a RecallHistoryResult, not a raw dict."""

import json
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from agentarea_execution.workflows.agent import context_tools
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.models import ToolCall
from temporalio import workflow

RECALLED = {
    "events": [
        {"event_type": "tool.result", "data": {"tool_name": "search"}, "created_at": "2026-10-13"}
    ],
    "total_count": 1,
    "summary": "1 event",
}


@pytest.fixture(autouse=True)
def _workflow_logger(monkeypatch):
    # workflow.logger needs the Temporal event loop; these tests run outside it.
    monkeypatch.setattr(workflow, "logger", MagicMock())


@pytest.fixture
def temporal_conversion(monkeypatch):
    """Decode the payload the way Temporal does: a dict unless a result_type is named."""

    async def execute_activity(_activity: str, *, result_type: Any = None, **_: Any) -> Any:
        return result_type.model_validate(RECALLED) if result_type else dict(RECALLED)

    monkeypatch.setattr(context_tools.workflow, "execute_activity", execute_activity)


@pytest.mark.asyncio
async def test_recalled_events_reach_the_model(temporal_conversion):
    instance = AgentExecutionWorkflow()
    instance.state.task_id = str(uuid4())
    instance.state.workspace_id = "ws-1"
    call = ToolCall(
        id="call-1", function={"name": "recall_history", "arguments": json.dumps({"limit": 5})}
    )

    await instance._execute_recall_history(call)

    [message] = instance.state.messages
    assert "Failed to recall history" not in message.content
    assert "tool.result" in message.content
