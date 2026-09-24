"""llm.call.completed carries both what the customer pays and what the provider charged.

``cost`` is in the billing currency once customer pricing converts it, so usage
projection can no longer read provider spend from it. ``provider_cost_usd`` is
the pre-conversion figure, carried alongside.
"""

import logging
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from agentarea_execution.models import LLMCallResult, LLMUsage
from agentarea_execution.workflows import agent_execution_workflow as workflow_module
from agentarea_execution.workflows.helpers import BudgetTracker, EventManager


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setattr(workflow_module.workflow, "logger", logging.getLogger("test-llm-call"))
    flow = workflow_module.AgentExecutionWorkflow()
    flow.state.task_id = "task-1"
    flow.state.agent_id = "agent-1"
    flow.state.execution_id = "execution-1"
    flow.state.user_context_data = {"user_id": "user", "workspace_id": "workspace"}
    flow.state.agent_config = {"model_id": "model-1"}
    flow.state.resolved_model = {"model_name": "m", "managed_by": "platform"}
    flow.state.effective_policy = {"tokens": {"max_tokens": 1000}}
    flow.event_manager = EventManager("task-1", "agent-1", "execution-1")
    flow.budget_tracker = BudgetTracker(Decimal("100"))
    flow._publish_events_immediately = AsyncMock()
    return flow


def _completed(flow):
    return next(
        event["data"]
        for event in flow.event_manager.get_pending_events()
        if event["event_type"] == "llm.call.completed"
    )


async def test_event_carries_converted_and_provider_cost(monkeypatch, flow):
    result = LLMCallResult(
        content="hi",
        cost=Decimal("1.90"),
        provider_cost_usd=Decimal("0.02"),
        currency="RUB",
        usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    monkeypatch.setattr(
        workflow_module.workflow, "execute_activity", AsyncMock(return_value=result)
    )

    await flow._call_llm()

    data = _completed(flow)
    assert data["cost"] == Decimal("1.90")
    assert data["provider_cost_usd"] == "0.02"
    assert flow.budget_tracker.cost == Decimal("1.90")
    assert flow.budget_tracker.currency == "RUB"


async def test_result_from_before_the_field_existed_reports_none(monkeypatch, flow):
    legacy = {
        "content": "hi",
        "role": "assistant",
        "cost": "0.02",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    monkeypatch.setattr(
        workflow_module.workflow, "execute_activity", AsyncMock(return_value=legacy)
    )

    await flow._call_llm()

    data = _completed(flow)
    assert data["provider_cost_usd"] is None
    # Recorded before results carried managed_by: the cache is all there is.
    assert data["managed_by"] == "platform"
    assert flow.budget_tracker.currency is None


def _through_temporal(result: LLMCallResult) -> LLMCallResult:
    """Serialize and deserialize the way the activity result reaches the workflow."""
    from temporalio.contrib.pydantic import pydantic_data_converter

    converter = pydantic_data_converter.payload_converter
    return converter.from_payload(converter.to_payload(result), LLMCallResult)


async def test_managed_by_comes_from_the_call_when_model_resolution_failed(monkeypatch, flow):
    """resolve_model failed, so the cache is empty; the activity resolved from the DB."""
    flow.state.resolved_model = None
    result = _through_temporal(
        LLMCallResult(
            content="hi",
            cost=Decimal("1.90"),
            provider_cost_usd=Decimal("0.02"),
            currency="RUB",
            managed_by="platform",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
    )
    monkeypatch.setattr(
        workflow_module.workflow, "execute_activity", AsyncMock(return_value=result)
    )

    await flow._call_llm()

    assert _completed(flow)["managed_by"] == "platform"


async def test_a_tenant_key_reported_by_the_call_is_not_overridden_by_the_cache(monkeypatch, flow):
    """None from the call means the tenant's key, not "unknown, ask the cache"."""
    result = _through_temporal(
        LLMCallResult(
            content="hi",
            cost=Decimal("0.02"),
            managed_by=None,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
    )
    monkeypatch.setattr(
        workflow_module.workflow, "execute_activity", AsyncMock(return_value=result)
    )

    await flow._call_llm()

    assert _completed(flow)["managed_by"] is None
