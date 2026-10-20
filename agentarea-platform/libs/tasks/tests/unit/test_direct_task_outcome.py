from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.money import to_money
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    ExecutionLimitsPolicy,
    TokenPolicy,
)
from agentarea_tasks.direct_task_manager import DirectTaskManager
from agentarea_tasks.domain.models import AgentTask


def _model(llm):
    """The agent's model as ``_resolve_agent`` hands it over: priced, not yet connected."""
    return SimpleNamespace(
        input_cost_per_token=to_money("0.000001"),
        output_cost_per_token=to_money("0.000002"),
        connect=AsyncMock(return_value=llm),
    )


@pytest.mark.asyncio
async def test_iteration_limit_is_failed_in_direct_execution():
    repository = AsyncMock()
    manager = DirectTaskManager(repository)
    llm = SimpleNamespace(
        complete=AsyncMock(
            return_value=SimpleNamespace(
                content="",
                cost=0,
                usage=SimpleNamespace(
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                ),
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {"name": "unknown", "arguments": "{}"},
                    }
                ],
            )
        )
    )
    manager._resolve_agent = AsyncMock(return_value=(_model(llm), "", [], "model-1", None))
    task = AgentTask(
        title="Task",
        description="Task",
        query="Task",
        user_id=str(uuid4()),
        workspace_id=str(uuid4()),
        agent_id=uuid4(),
        status="running",
        created_at=datetime.now(UTC),
        effective_policy=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd=to_money("1.00")),
            tokens=TokenPolicy(max_tokens=1000, max_tokens_per_call=100),
            execution=ExecutionLimitsPolicy(
                max_model_turns=10,
                max_tool_calls_per_turn=10,
                max_tool_calls_total=100,
            ),
        ).to_json_dict(),
    )

    await manager._execute(task)

    assert task.status == "failed"
    assert task.error_message == "Maximum iterations reached (10)"
    assert task.result == {
        "success": False,
        "status": "failed",
        "failure_reason": "iteration_limit",
        "error": "Maximum iterations reached (10)",
        "total_cost": "0",
        "own_cost": "0",
        "total_tokens": 20,
        "total_tool_calls": 10,
    }
    assert llm.complete.await_count == 10
    repository.update_status.assert_awaited_once_with(
        task.id,
        "failed",
        result=task.result,
        error="Maximum iterations reached (10)",
    )


@pytest.mark.asyncio
async def test_completion_does_not_consume_direct_tool_call_quota():
    repository = AsyncMock()
    manager = DirectTaskManager(repository)
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    llm = SimpleNamespace(
        complete=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    content="",
                    cost=0,
                    usage=usage,
                    tool_calls=[
                        {
                            "id": "call-tool",
                            "function": {"name": "unknown", "arguments": "{}"},
                        }
                    ],
                ),
                SimpleNamespace(
                    content="",
                    cost=0,
                    usage=usage,
                    tool_calls=[
                        {
                            "id": "call-completion",
                            "function": {
                                "name": "completion",
                                "arguments": '{"result":"done"}',
                            },
                        }
                    ],
                ),
            ]
        )
    )
    manager._resolve_agent = AsyncMock(return_value=(_model(llm), "", [], "model-1", None))
    task = AgentTask(
        title="Task",
        description="Task",
        query="Task",
        user_id=str(uuid4()),
        workspace_id=str(uuid4()),
        agent_id=uuid4(),
        status="running",
        created_at=datetime.now(UTC),
        effective_policy=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd=to_money("1.00")),
            tokens=TokenPolicy(max_tokens=1000, max_tokens_per_call=100),
            execution=ExecutionLimitsPolicy(
                max_model_turns=3,
                max_tool_calls_per_turn=1,
                max_tool_calls_total=1,
            ),
        ).to_json_dict(),
    )

    await manager._execute(task)

    assert task.status == "completed"
    assert task.result == {
        "response": "done",
        "total_cost": "0",
        "own_cost": "0",
        "total_tokens": 4,
        "total_tool_calls": 1,
    }
    assert llm.complete.await_count == 2
    repository.update_status.assert_awaited_once_with(
        task.id,
        "completed",
        result=task.result,
    )


class _Billing:
    """Billing in EUR: holds each platform call, prices 1 USD of it at 142.5 EUR."""

    def __init__(self):
        self.authorizations = []

    def currency(self):
        return "EUR"

    async def authorize(self, **request):
        self.authorizations.append(request)
        return SimpleNamespace(
            allowed=True,
            code="ok",
            reason="",
            hold_id=f"hold-{len(self.authorizations)}",
            amount=to_money("10.00"),
            currency="EUR",
            expires_at=None,
        )

    async def capture(self, **request):
        raise AssertionError("the settlement worker captures")

    async def void(self, *, hold_id):
        return None

    async def quote(self, lines):
        return [
            SimpleNamespace(amount=line.vendor_cost * to_money("142.5"), code="ok")
            for line in lines
        ]


@pytest.fixture
def billing(monkeypatch):
    from agentarea_common.extensions import tool_billing
    from agentarea_common.extensions.registry import ExtensionRegistry

    installed = _Billing()
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "EUR")
    monkeypatch.setattr(ExtensionRegistry, "_factories", {"tool_billing": lambda: installed})
    tool_billing.get_tool_billing.cache_clear()
    yield installed
    tool_billing.get_tool_billing.cache_clear()


def _platform_llm(cost, tool_calls):
    return SimpleNamespace(
        complete=AsyncMock(
            return_value=SimpleNamespace(
                content="",
                cost=cost,
                usage=SimpleNamespace(
                    prompt_tokens=3,
                    completion_tokens=2,
                    total_tokens=5,
                    cached_prompt_tokens=0,
                    cache_creation_tokens=0,
                ),
                tool_calls=tool_calls,
            )
        ),
    )


def _task(run_budget: str) -> AgentTask:
    return AgentTask(
        title="Task",
        description="Task",
        query="Task",
        user_id=str(uuid4()),
        workspace_id=str(uuid4()),
        agent_id=uuid4(),
        status="running",
        created_at=datetime.now(UTC),
        effective_policy=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd=to_money(run_budget)),
            tokens=TokenPolicy(max_tokens=1000, max_tokens_per_call=100),
            execution=ExecutionLimitsPolicy(
                max_model_turns=3,
                max_tool_calls_per_turn=1,
                max_tool_calls_total=1,
            ),
        ).to_json_dict(),
    )


@pytest.mark.asyncio
async def test_direct_execution_holds_each_call_and_counts_billings_price(billing):
    """On this engine too a platform call is held and its line is billing's price."""
    repository = AsyncMock()
    manager = DirectTaskManager(repository)
    completion = [
        {
            "id": "call-completion",
            "function": {"name": "completion", "arguments": '{"result":"done"}'},
        }
    ]
    model = _model(_platform_llm(0.01, completion))
    manager._resolve_agent = AsyncMock(return_value=(model, "", [], "model-1", MANAGED_BY_PLATFORM))
    task = _task("100.00")

    await manager._execute(task)

    assert task.status == "completed"
    assert task.result["total_cost"] == "1.425"
    [hold] = billing.authorizations
    assert (hold["kind"], hold["tool"]) == ("model", "model-1")
    [funding] = model.connect.await_args.args
    assert (funding.hold_id, funding.platform_funded) == ("hold-1", True)
    [line] = repository.record_costs.await_args.args[0]
    assert (line.amount, line.currency, line.agent_id) == (to_money("1.425"), "EUR", task.agent_id)
    assert (line.subject_id, line.payer.value, line.estimate) == ("model-1", "platform", True)
    assert line.evidence["hold_id"] == "hold-1" and line.evidence["settle"] == "capture"
    assert (line.vendor_cost, line.vendor_currency) == (to_money("0.01"), "USD")


@pytest.mark.asyncio
async def test_direct_run_budget_error_names_the_billing_currency(billing):
    repository = AsyncMock()
    manager = DirectTaskManager(repository)
    manager._resolve_agent = AsyncMock(
        return_value=(_model(_platform_llm(0.1, [])), "", [], "model-1", MANAGED_BY_PLATFORM)
    )
    task = _task("1.00")

    await manager._execute(task)

    error = repository.update_status.await_args.kwargs["error"]
    assert error == "run budget exceeded: 14.25 EUR/1.00 EUR"


@pytest.mark.asyncio
async def test_a_cap_reached_mid_run_stops_the_next_direct_model_call(monkeypatch):
    from agentarea_tasks import direct_task_manager
    from agentarea_tasks.model_spend_caps import SpendCapReachedError

    reads: list = []

    async def cap_reached_after_the_first_call(session, user_context, budget, agent_id):
        reads.append(agent_id)
        if len(reads) > 1:
            raise SpendCapReachedError("Workspace monthly LLM spend cap reached (2 USD/2 USD)")

    monkeypatch.setattr(
        direct_task_manager, "refuse_model_call_at_spend_cap", cap_reached_after_the_first_call
    )
    manager = DirectTaskManager(AsyncMock())
    llm = SimpleNamespace(
        complete=AsyncMock(
            return_value=SimpleNamespace(
                content="",
                cost=0,
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                tool_calls=[
                    {"id": "call-1", "function": {"name": "unknown", "arguments": "{}"}}
                ],
            )
        )
    )
    manager._resolve_agent = AsyncMock(return_value=(_model(llm), "", [], "model-1", None))
    agent_id = uuid4()
    task = AgentTask(
        title="Task",
        description="Task",
        query="Task",
        user_id=str(uuid4()),
        workspace_id=str(uuid4()),
        agent_id=agent_id,
        status="running",
        created_at=datetime.now(UTC),
        effective_policy=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd=to_money("1.00")),
            tokens=TokenPolicy(max_tokens=1000, max_tokens_per_call=100),
            execution=ExecutionLimitsPolicy(
                max_model_turns=10,
                max_tool_calls_per_turn=10,
                max_tool_calls_total=100,
            ),
        ).to_json_dict(),
    )

    await manager._execute(task)

    assert reads == [agent_id, agent_id]
    assert llm.complete.await_count == 1
    assert task.status == "failed"
    assert "monthly LLM spend cap reached" in (task.error_message or "")
