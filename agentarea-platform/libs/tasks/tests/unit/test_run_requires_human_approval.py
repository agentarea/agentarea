"""A run started with ``requires_human_approval`` is gated by the policy engine.

The flag used to be written into task metadata and a workflow field nothing read,
so the run executed its tools unasked (#545). It is now a tighten-only task
policy layer, which reaches the same approval gate every policy approval does.
REST and MCP start runs through ``start_run``/``reserve_run``; A2A hands a
pre-built task with the flag in its metadata to ``submit_task``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_governance.domain.policies import (
    ApprovalPolicy,
    EffectivePolicy,
    PolicyDocument,
    PolicyResolver,
)
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.schemas.dto import RunCreate
from agentarea_tasks.task_service import TaskService

WORKSPACE = "ws-acme"
USER = "user-123"

_BASELINE = PolicyDocument.model_validate(
    {
        "budget": {"run_budget_usd": "50.00"},
        "tokens": {"max_tokens": 20_000_000, "max_tokens_per_call": 100_000},
        "execution": {
            "max_model_turns": 100,
            "max_tool_calls_per_turn": 10,
            "max_tool_calls_total": 1000,
        },
    }
)


class _Resolver:
    """The workspace baseline with the task layer merged by the real resolver."""

    async def resolve(
        self,
        *,
        workspace_id: str,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
        task_policy: PolicyDocument | None = None,
        user_id: str | None = None,
    ) -> EffectivePolicy:
        return PolicyResolver().resolve([_BASELINE, task_policy])


def _service() -> tuple[TaskService, MagicMock]:
    agent = MagicMock(id=uuid4(), model_id="gpt-4o-mini")
    agent.name = "stub-agent"
    agent_repo = MagicMock()
    agent_repo.get = AsyncMock(return_value=agent)
    task_repo = MagicMock()
    task_repo.find_active_by_agent_and_chat = AsyncMock(return_value=[])

    def create_repository(cls):
        if cls is TaskRepository:
            return task_repo
        if cls is AgentRepository:
            return agent_repo
        raise AssertionError(f"unexpected repository request: {cls}")

    repository_factory = MagicMock()
    repository_factory.create_repository = create_repository
    repository_factory.user_context.user_id = USER

    task_manager = MagicMock()
    task_manager.supports_scheduling = True
    task_manager.submit_task = AsyncMock(side_effect=lambda task: task)

    service = TaskService(
        repository_factory=repository_factory,
        event_broker=AsyncMock(),
        task_manager=task_manager,
        policy_resolver=_Resolver(),
    )
    service.create_task = AsyncMock(side_effect=lambda task: task)
    return service, task_manager


def _approval(task: AgentTask) -> dict[str, Any]:
    assert task.effective_policy is not None
    return task.effective_policy.get("approval") or {}


def _requested_approval(task: AgentTask) -> dict[str, Any]:
    snapshot = task.metadata["governance_snapshot"]
    return snapshot["requested_policy"].get("approval") or {}


@pytest.mark.asyncio
async def test_start_run_with_the_flag_requires_approval_in_the_effective_policy():
    service, task_manager = _service()

    await service.start_run(
        RunCreate(agent_id=uuid4(), description="deploy", requires_human_approval=True),
        workspace_id=WORKSPACE,
        user_id=USER,
        created_via="mcp",
    )

    submitted = task_manager.submit_task.await_args.args[0]
    assert _approval(submitted)["requires_human_approval"] is True
    assert _requested_approval(submitted)["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_reserve_run_with_the_flag_requires_approval_in_the_effective_policy():
    service, _ = _service()

    task = await service.reserve_run(
        RunCreate(agent_id=uuid4(), description="deploy", requires_human_approval=True),
        workspace_id=WORKSPACE,
        user_id=USER,
        task_id=uuid4(),
    )

    assert _approval(task)["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_a2a_metadata_flag_requires_approval_in_the_effective_policy():
    service, task_manager = _service()
    task = AgentTask(
        id=uuid4(),
        title="deploy",
        description="deploy",
        query="deploy",
        user_id=USER,
        workspace_id=WORKSPACE,
        agent_id=uuid4(),
        status="submitted",
        task_parameters={},
        metadata={"created_via": "a2a_protocol", "requires_human_approval": True},
    )

    await service.submit_task(task)

    submitted = task_manager.submit_task.await_args.args[0]
    assert _approval(submitted)["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_the_flag_joins_a_caller_task_policy_instead_of_replacing_it():
    service, task_manager = _service()

    await service.start_run(
        RunCreate(
            agent_id=uuid4(),
            description="deploy",
            requires_human_approval=True,
            task_policy=PolicyDocument(approval=ApprovalPolicy(escalation_rules=["deploy_*"])),
        ),
        workspace_id=WORKSPACE,
        user_id=USER,
    )

    approval = _approval(task_manager.submit_task.await_args.args[0])
    assert approval["requires_human_approval"] is True
    assert approval["escalation_rules"] == ["deploy_*"]


@pytest.mark.asyncio
async def test_without_the_flag_no_approval_is_added():
    service, task_manager = _service()

    await service.start_run(
        RunCreate(agent_id=uuid4(), description="deploy"),
        workspace_id=WORKSPACE,
        user_id=USER,
    )

    assert _approval(task_manager.submit_task.await_args.args[0]) == {}
