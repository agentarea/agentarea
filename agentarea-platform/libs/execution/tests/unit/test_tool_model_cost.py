"""A tool's platform-model spend joins the run budget and task total; service cost does not."""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_execution.models import MCPToolResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import BudgetTracker
from agentarea_execution.workflows.models import ToolCall
from temporalio import workflow


@pytest.fixture(autouse=True)
def _workflow_logger(monkeypatch):
    # workflow.logger needs the Temporal event loop; these tests run outside it.
    monkeypatch.setattr(workflow, "logger", MagicMock())


def _workflow(result: MCPToolResult) -> AgentExecutionWorkflow:
    instance = AgentExecutionWorkflow()
    instance.state.task_id = str(uuid4())
    instance.state.workspace_id = "ws-1"
    instance.state.user_context_data = {"user_id": "u-1", "workspace_id": "ws-1"}
    instance.state.agent_config = {"tools": []}
    instance.budget_tracker = BudgetTracker(budget_usd=Decimal("1000"))
    instance.budget_tracker.add_cost(Decimal("2"))
    instance.event_manager = MagicMock()
    instance._publish_events_immediately = AsyncMock()
    instance._gate_tool_call = AsyncMock(return_value=(True, False))
    instance._maybe_offload_output = AsyncMock(side_effect=lambda text, _id: text)
    instance._execute_governed_tool = AsyncMock(return_value=result)
    return instance


def _call() -> ToolCall:
    return ToolCall(
        id="call-1",
        function={"name": "media_generate_image", "arguments": json.dumps({"prompt": "a cat"})},
    )


@pytest.mark.asyncio
async def test_model_cost_is_added_to_the_run_budget():
    instance = _workflow(MCPToolResult(success=True, result="{}", model_cost=Decimal("150")))

    await instance._execute_mcp_tool(_call())

    assert instance.budget_tracker is not None
    assert instance.budget_tracker.cost == Decimal("152")
    assert instance.state.service_cost_used == 0
    [(_, completed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert completed["model_cost"] == "150"


@pytest.mark.asyncio
async def test_a_failed_tool_still_charges_the_model_it_paid_for():
    """The image was generated (and paid for) before saving it failed."""
    instance = _workflow(MCPToolResult(success=False, error="disk full", model_cost=Decimal("4")))

    await instance._execute_mcp_tool(_call())

    assert instance.budget_tracker is not None
    assert instance.budget_tracker.cost == Decimal("6")
    [(_, failed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert failed["success"] is False
    assert failed["model_cost"] == "4"


@pytest.mark.asyncio
async def test_a_result_without_model_cost_leaves_the_budget_alone():
    """Older histories carry no model_cost: the replayed run takes no new branch."""
    instance = _workflow(MCPToolResult(success=True, result="{}", service_cost=Decimal("0.5")))

    await instance._execute_mcp_tool(_call())

    assert instance.budget_tracker is not None
    assert instance.budget_tracker.cost == Decimal("2")
    assert instance.state.service_cost_used == Decimal("0.5")
    [(_, completed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert "model_cost" not in completed


@pytest.mark.asyncio
async def test_a_metered_call_joins_the_budget_and_says_who_paid():
    instance = _workflow(
        MCPToolResult(
            success=True,
            result="[]",
            cost=Decimal("0.74"),
            payer="platform",
            cost_metered=True,
        )
    )

    await instance._execute_mcp_tool(_call())

    assert instance.budget_tracker is not None
    assert instance.budget_tracker.cost == Decimal("2.74")
    [(_, completed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert (completed["payer"], completed["cost"], completed["cost_metered"]) == (
        "platform",
        "0.74",
        True,
    )
    assert "managed_by" not in completed


@pytest.mark.asyncio
async def test_a_platform_call_recorded_before_the_layer_metered_every_call_still_counts():
    instance = _workflow(
        MCPToolResult.model_validate(
            {"success": True, "result": "[]", "cost": "0.74", "managed_by": "platform"}
        )
    )

    await instance._execute_mcp_tool(_call())

    assert instance.budget_tracker.cost == Decimal("2.74")
    [(_, completed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert completed["cost"] == "0.74"


@pytest.mark.asyncio
async def test_a_call_on_a_workspaces_own_connection_carries_no_platform_fields():
    instance = _workflow(MCPToolResult(success=True, result="{}"))

    await instance._execute_mcp_tool(_call())

    [(_, completed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert not {"managed_by", "payer", "cost", "cost_metered"} & set(completed)


@pytest.mark.asyncio
async def test_a_replayed_retry_is_marked_on_its_tool_result():
    instance = _workflow(
        MCPToolResult(success=True, result="[]", cost_metered=True, replayed=True, attempt=2)
    )

    await instance._execute_mcp_tool(_call())

    [(_, completed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert (completed["replayed"], completed["attempt"]) == (True, 2)


@pytest.mark.asyncio
async def test_a_failed_replayed_retry_is_marked_too():
    instance = _workflow(
        MCPToolResult(success=False, error="502", result="", replayed=True, attempt=3)
    )

    await instance._execute_mcp_tool(_call())

    [(_, failed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert (failed["success"], failed["replayed"], failed["attempt"]) == (False, True, 3)


@pytest.mark.asyncio
async def test_a_first_attempt_carries_neither_field():
    instance = _workflow(MCPToolResult(success=True, result="{}"))

    await instance._execute_mcp_tool(_call())

    [(_, completed)] = [c.args for c in instance.event_manager.add_event.call_args_list[1:]]
    assert not {"replayed", "attempt"} & set(completed)
