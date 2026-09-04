"""Unit tests for the task submission paths in TaskService.

These tests pin the contract between `submit_task`, `create_and_execute_task_with_workflow`,
and `task_manager.submit_task` so that A2A, MCP, and REST stay aligned. Drift here was the
root cause of A2A losing channel routing and metadata defaults.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    ExecutionLimitsPolicy,
    PolicyDocument,
    PolicyValidationError,
    TokenPolicy,
)
from agentarea_tasks.domain.exceptions import AgentModelNotConfiguredError
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.schemas.dto import RunCreate, RunExecutionConfig
from agentarea_tasks.task_service import TaskService


def _make_service(temporal_executor=None):
    """Build a TaskService with mocked deps. Returns (service, mocks)."""
    task_repo = MagicMock()
    task_repo.create_task = AsyncMock(side_effect=lambda t: t)
    task_repo.find_active_by_agent_and_chat = AsyncMock(return_value=[])

    agent_stub = MagicMock(id=uuid4())
    agent_stub.name = "stub-agent"  # MagicMock(name=...) is the mock's own name, not a field
    agent_stub.tools = [
        {
            "type": "code",
            "name": "agentarea/shell",
            "settings": {},
        }
    ]
    agent_repo = MagicMock()
    agent_repo.get = AsyncMock(return_value=agent_stub)

    repo_factory = MagicMock()

    def create_repository(cls):
        if cls is TaskRepository:
            return task_repo
        if cls is AgentRepository:
            return agent_repo
        raise AssertionError(f"unexpected repository request: {cls}")

    repo_factory.create_repository = create_repository

    event_broker = AsyncMock()

    task_manager = MagicMock()

    async def _submit(t):
        t.status = "running"
        t.execution_id = f"task-{t.id}"
        return t

    task_manager.submit_task = AsyncMock(side_effect=_submit)
    task_manager.temporal_executor = temporal_executor

    policy_resolver = MagicMock()
    policy_resolver.resolve = AsyncMock(
        return_value=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd="50.00"),
            tokens=TokenPolicy(max_tokens=20_000_000, max_tokens_per_call=100_000),
            execution=ExecutionLimitsPolicy(
                max_model_turns=100,
                max_tool_calls_per_turn=10,
                max_tool_calls_total=1000,
            ),
            source_policy_ids=["workspace-runtime-baseline"],
        )
    )

    service = TaskService(
        repository_factory=repo_factory,
        event_broker=event_broker,
        task_manager=task_manager,
        policy_resolver=policy_resolver,
    )
    # Short-circuit create_task for unit isolation (bypasses audit decorator + db plumbing).
    service.create_task = AsyncMock(side_effect=lambda t: t)

    return service, {
        "task_repo": task_repo,
        "agent_repo": agent_repo,
        "task_manager": task_manager,
        "event_broker": event_broker,
    }


def _build_task(**overrides):
    base = {
        "id": uuid4(),
        "title": "A2A Message Task",
        "description": "Hello from A2A",
        "query": "Hello from A2A",
        "user_id": "user-123",
        "workspace_id": "ws-abc",
        "agent_id": uuid4(),
        "status": "submitted",
        "task_parameters": {},
        "metadata": {
            "task_source": "a2a_protocol",
            "a2a_method": "message/send",
        },
    }
    base.update(overrides)
    return AgentTask(**base)


@pytest.mark.asyncio
async def test_submit_task_routes_through_canonical_method_and_invokes_task_manager():
    """submit_task() must end at task_manager.submit_task and produce a stored task."""
    service, mocks = _make_service()
    task = _build_task()

    result = await service.submit_task(task)

    mocks["agent_repo"].get.assert_awaited_once_with(task.agent_id)
    mocks["task_manager"].submit_task.assert_awaited_once()
    submitted_arg = mocks["task_manager"].submit_task.await_args.args[0]
    assert isinstance(submitted_arg, AgentTask)
    assert result.execution_id is not None


@pytest.mark.asyncio
async def test_submit_task_preserves_caller_provided_id_metadata_and_parameters():
    """A2A pre-builds the AgentTask. The id, metadata and task_parameters must survive."""
    service, mocks = _make_service()
    pre_id = uuid4()
    task = _build_task(
        id=pre_id,
        task_parameters={"channel_origin": {"chat_id": "c-99"}, "tone": "warm"},
        metadata={"task_source": "a2a_protocol", "request_id": "req-7"},
    )

    await service.submit_task(task)

    submitted_arg = mocks["task_manager"].submit_task.await_args.args[0]
    assert submitted_arg.id == pre_id
    assert submitted_arg.task_parameters == {
        "channel_origin": {"chat_id": "c-99"},
        "tone": "warm",
    }
    # Caller metadata preserved AND merged with canonical defaults
    assert submitted_arg.metadata["task_source"] == "a2a_protocol"
    assert submitted_arg.metadata["request_id"] == "req-7"


@pytest.mark.asyncio
async def test_create_and_execute_sets_default_metadata():
    """REST callers rely on metadata.created_via, agent_name, requires_human_approval defaults."""
    service, mocks = _make_service()
    agent_id = uuid4()

    await service.create_and_execute_task_with_workflow(
        agent_id=agent_id,
        description="generate vk post",
        workspace_id="ws-abc",
        user_id="user-123",
    )

    submitted = mocks["task_manager"].submit_task.await_args.args[0]
    assert submitted.metadata["created_via"] == "api"
    assert submitted.metadata["requires_human_approval"] is False
    snapshot = submitted.metadata["governance_snapshot"]
    assert snapshot["resolved_execution"] == snapshot["effective_policy"]["execution"]
    assert snapshot["effective_policy"]["execution"]["max_model_turns"] == 100
    assert snapshot["effective_policy"] == submitted.effective_policy


@pytest.mark.asyncio
async def test_typed_execution_request_is_snapshotted_without_free_form_parameter():
    service, mocks = _make_service()

    await service.start_run(
        RunCreate(
            agent_id=uuid4(),
            description="Use an explicit turn ceiling",
            execution=RunExecutionConfig(max_model_turns=25),
        ),
        workspace_id="ws-abc",
        user_id="user-123",
    )

    submitted = mocks["task_manager"].submit_task.await_args.args[0]
    snapshot = submitted.metadata["governance_snapshot"]
    assert submitted.task_parameters.get("max_iterations") is None
    assert snapshot["requested_execution"]["max_model_turns"] == 25


@pytest.mark.asyncio
async def test_typed_and_legacy_execution_requests_cannot_conflict():
    service, _ = _make_service()

    with pytest.raises(PolicyValidationError, match="conflicts"):
        await service.start_run(
            RunCreate(
                agent_id=uuid4(),
                description="Conflicting ceilings",
                parameters={"max_iterations": 30},
                execution=RunExecutionConfig(max_model_turns=25),
            ),
            workspace_id="ws-abc",
            user_id="user-123",
        )


@pytest.mark.asyncio
async def test_typed_execution_and_task_policy_cannot_conflict():
    service, _ = _make_service()

    with pytest.raises(PolicyValidationError, match="conflicts"):
        await service.start_run(
            RunCreate(
                agent_id=uuid4(),
                description="Conflicting typed ceilings",
                execution=RunExecutionConfig(max_model_turns=25),
                task_policy=PolicyDocument(execution=ExecutionLimitsPolicy(max_model_turns=20)),
            ),
            workspace_id="ws-abc",
            user_id="user-123",
        )


@pytest.mark.asyncio
async def test_legacy_iteration_limit_is_translated_and_not_persisted_in_parameters():
    service, mocks = _make_service()

    await service.start_run(
        RunCreate(
            agent_id=uuid4(),
            description="Legacy client",
            parameters={"max_iterations": 30, "custom": "kept"},
        ),
        workspace_id="ws-abc",
        user_id="user-123",
    )

    submitted = mocks["task_manager"].submit_task.await_args.args[0]
    assert submitted.task_parameters == {"custom": "kept"}
    assert submitted.metadata["governance_snapshot"]["requested_execution"]["max_model_turns"] == 30


@pytest.mark.asyncio
async def test_delegated_task_cannot_loosen_parent_execution_policy():
    service, _ = _make_service()
    parent_policy = EffectivePolicy(
        budget=BudgetPolicy(run_budget_usd="50.00"),
        tokens=TokenPolicy(max_tokens=20_000_000, max_tokens_per_call=100_000),
        execution=ExecutionLimitsPolicy(
            max_model_turns=10,
            max_tool_calls_per_turn=10,
            max_tool_calls_total=1000,
        ),
    )

    with pytest.raises(
        PolicyValidationError,
        match="max_model_turns cannot loosen",
    ):
        await service.create_task_with_policy(
            agent_id=uuid4(),
            description="Delegated work",
            workspace_id="ws-abc",
            user_id="user-123",
            upper_bound_policy=parent_policy,
        )


def test_run_contract_has_no_sandbox_policy_toggle() -> None:
    removed_field = "package" + "_install"

    assert removed_field not in RunCreate.model_fields


@pytest.mark.asyncio
async def test_submit_task_routes_to_active_workflow_when_chat_id_present():
    """submit_task with channel_origin.chat_id must attempt routing before creating a new task."""
    executor = MagicMock()
    executor.send_workflow_command = AsyncMock(return_value=True)
    service, mocks = _make_service(temporal_executor=executor)

    candidate = MagicMock(
        id=uuid4(),
        execution_id="task-existing",
        description="prev",
        user_id="user-123",
        workspace_id="ws-abc",
        agent_id=uuid4(),
        parameters={},
    )
    mocks["task_repo"].find_active_by_agent_and_chat = AsyncMock(return_value=[candidate])

    task = _build_task(task_parameters={"channel_origin": {"chat_id": "c-99"}})

    result = await service.submit_task(task)

    # Routed task short-circuits — no new submit_task on task_manager
    mocks["task_manager"].submit_task.assert_not_awaited()
    executor.send_workflow_command.assert_awaited_once()
    assert result.status == "routed"
    assert result.execution_id == "task-existing"


@pytest.mark.asyncio
async def test_create_and_execute_routes_to_active_workflow_when_chat_id_present():
    """REST path also routes to active workflow when channel_origin.chat_id is set."""
    executor = MagicMock()
    executor.send_workflow_command = AsyncMock(return_value=True)
    service, mocks = _make_service(temporal_executor=executor)

    candidate = MagicMock(
        id=uuid4(),
        execution_id="task-existing",
        description="prev",
        user_id="user-123",
        workspace_id="ws-abc",
        agent_id=uuid4(),
        parameters={},
    )
    mocks["task_repo"].find_active_by_agent_and_chat = AsyncMock(return_value=[candidate])

    result = await service.create_and_execute_task_with_workflow(
        agent_id=uuid4(),
        description="follow-up",
        workspace_id="ws-abc",
        parameters={"channel_origin": {"chat_id": "c-99"}},
        user_id="user-123",
    )

    mocks["task_manager"].submit_task.assert_not_awaited()
    executor.send_workflow_command.assert_awaited_once()
    assert result.status == "routed"


def _model_less_agent():
    agent = MagicMock(id=uuid4())
    agent.name = "no-model-agent"
    agent.model_id = None  # installed catalog agent with no matching workspace model
    agent.tools = [
        {
            "type": "code",
            "name": "agentarea/shell",
            "settings": {},
        }
    ]
    return agent


@pytest.mark.asyncio
async def test_create_and_execute_blocks_agent_without_model():
    """A run for an agent with no model must fail fast, not dispatch to Temporal."""
    service, mocks = _make_service()
    agent = _model_less_agent()
    mocks["agent_repo"].get = AsyncMock(return_value=agent)

    with pytest.raises(AgentModelNotConfiguredError):
        await service.create_and_execute_task_with_workflow(
            agent_id=agent.id,
            description="do x",
            workspace_id="ws-abc",
            user_id="user-123",
        )

    mocks["task_manager"].submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_override_in_parameters_bypasses_model_guard():
    """A per-run model_override satisfies the model requirement."""
    service, mocks = _make_service()
    agent = _model_less_agent()
    mocks["agent_repo"].get = AsyncMock(return_value=agent)

    await service.create_and_execute_task_with_workflow(
        agent_id=agent.id,
        description="do x",
        workspace_id="ws-abc",
        user_id="user-123",
        parameters={"model_override": "inst-override"},
    )

    mocks["task_manager"].submit_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_followup_routing_is_not_blocked_by_missing_model():
    """A follow-up routed to a live workflow reuses its model and skips the guard."""
    executor = MagicMock()
    executor.send_workflow_command = AsyncMock(return_value=True)
    service, mocks = _make_service(temporal_executor=executor)
    agent = _model_less_agent()
    mocks["agent_repo"].get = AsyncMock(return_value=agent)

    candidate = MagicMock(
        id=uuid4(),
        execution_id="task-existing",
        description="prev",
        user_id="user-123",
        workspace_id="ws-abc",
        agent_id=uuid4(),
        parameters={},
    )
    mocks["task_repo"].find_active_by_agent_and_chat = AsyncMock(return_value=[candidate])

    result = await service.create_and_execute_task_with_workflow(
        agent_id=agent.id,
        description="follow-up",
        workspace_id="ws-abc",
        parameters={"channel_origin": {"chat_id": "c-99"}},
        user_id="user-123",
    )

    assert result.status == "routed"
    mocks["task_manager"].submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_and_execute_accepts_task_id_override_for_a2a_callers():
    """A2A pre-assigns a task id (so the JSON-RPC response can echo it). The canonical method must honour it."""
    service, mocks = _make_service()
    pre_id = uuid4()

    await service.create_and_execute_task_with_workflow(
        agent_id=uuid4(),
        description="agent-to-agent ping",
        workspace_id="ws-abc",
        user_id="user-123",
        task_id=pre_id,
        title="A2A Message Task",
        metadata_overrides={"task_source": "a2a_protocol"},
    )

    submitted = mocks["task_manager"].submit_task.await_args.args[0]
    assert submitted.id == pre_id
    assert submitted.title == "A2A Message Task"
    assert submitted.metadata["task_source"] == "a2a_protocol"
    # Canonical defaults still applied
    assert submitted.metadata["created_via"] == "api"
    assert submitted.metadata["requires_human_approval"] is False


@pytest.mark.asyncio
async def test_start_run_forwards_reserved_id_and_trusted_attachment_metadata():
    service, mocks = _make_service()
    task_id = uuid4()
    agent_id = uuid4()
    attachments = [
        {
            "relative_path": "inputs/attachments/report.csv",
            "filename": "report.csv",
            "size": 12,
            "content_type": "text/csv",
            "sha256": "a" * 64,
        }
    ]

    await service.start_run(
        RunCreate(
            agent_id=agent_id,
            description="Analyze the attachment",
            parameters={"attachments": attachments},
        ),
        workspace_id="ws-abc",
        user_id="user-123",
        task_id=task_id,
        trusted_metadata={"workspace_attachments": attachments},
    )

    submitted = mocks["task_manager"].submit_task.await_args.args[0]
    assert submitted.id == task_id
    assert submitted.task_parameters["attachments"] == attachments
    assert submitted.metadata["workspace_attachments"] == attachments


@pytest.mark.asyncio
async def test_reserve_then_dispatch_persists_before_starting_workflow():
    service, mocks = _make_service()
    task_id = uuid4()
    agent_id = uuid4()
    reserved = MagicMock(id=task_id, status="preparing")
    service.create_task_with_policy = AsyncMock(return_value=reserved)

    task = await service.reserve_run(
        RunCreate(agent_id=agent_id, description="Analyze upload"),
        workspace_id="ws-abc",
        user_id="user-123",
        task_id=task_id,
        trusted_metadata={"workspace_attachments": [{"filename": "report.csv"}]},
    )

    assert task is reserved
    reserve_call = service.create_task_with_policy.await_args
    assert reserve_call.kwargs["task_id"] == task_id
    assert reserve_call.kwargs["status"] == "preparing"
    assert reserve_call.kwargs["require_model"] is True
    assert reserve_call.kwargs["metadata_overrides"]["workspace_attachments"] == [
        {"filename": "report.csv"}
    ]
    mocks["task_manager"].submit_task.assert_not_awaited()

    await service.dispatch_reserved_run(task)

    assert reserved.status == "running"
    mocks["task_manager"].submit_task.assert_awaited_once_with(reserved)
