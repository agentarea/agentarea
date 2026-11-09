"""A run may name the Codex or Claude Code client it runs on instead of its agent's own.

The agent's ``client_id`` is where its runs go by default; a run started with
``runner_client_id`` runs that one on the named client's runner instead, and a
client the caller may not use is refused before anything is persisted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_execution.models import RUNNER_CLIENT_METADATA_KEY
from agentarea_governance.domain.policies import EffectivePolicy, PolicyDocument, PolicyResolver
from agentarea_mcp.application import client_service
from agentarea_tasks.domain.exceptions import InvalidRunnerClientError
from agentarea_tasks.domain.models import TaskProvenance
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.schemas.dto import RunCreate
from agentarea_tasks.task_service import TaskService

WORKSPACE = "ws-acme"
USER = "user-123"
_STARTED = TaskProvenance.started_by(USER, via_api_key=False)

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


def _service(*, model_id: str | None, client_id: UUID | None) -> tuple[TaskService, MagicMock]:
    agent = MagicMock(id=uuid4(), model_id=model_id, client_id=client_id)
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


@pytest.fixture
def usable(monkeypatch: pytest.MonkeyPatch) -> set[UUID]:
    """The runner clients the caller may use; any other id is refused."""
    allowed: set[UUID] = set()

    async def usable_runner_client(repository_factory, client_id):
        return MagicMock(id=client_id) if client_id in allowed else None

    monkeypatch.setattr(client_service, "usable_runner_client", usable_runner_client)
    return allowed


@pytest.mark.asyncio
async def test_a_platform_agent_runs_on_the_named_client(usable: set[UUID]):
    runner = uuid4()
    usable.add(runner)
    service, task_manager = _service(model_id=None, client_id=None)

    await service.start_run(
        RunCreate(agent_id=uuid4(), description="fix the bug", runner_client_id=runner),
        workspace_id=WORKSPACE,
        user_id=USER,
        provenance=_STARTED,
    )

    submitted = task_manager.submit_task.await_args.args[0]
    assert submitted.metadata[RUNNER_CLIENT_METADATA_KEY] == str(runner)


@pytest.mark.asyncio
async def test_the_named_client_replaces_the_agents_own(usable: set[UUID]):
    runner = uuid4()
    usable.add(runner)
    service, task_manager = _service(model_id=None, client_id=uuid4())

    await service.start_run(
        RunCreate(agent_id=uuid4(), description="fix the bug", runner_client_id=runner),
        workspace_id=WORKSPACE,
        user_id=USER,
        provenance=_STARTED,
    )

    submitted = task_manager.submit_task.await_args.args[0]
    assert submitted.metadata[RUNNER_CLIENT_METADATA_KEY] == str(runner)


@pytest.mark.asyncio
async def test_without_a_named_client_the_run_goes_where_the_agent_runs(usable: set[UUID]):
    own = uuid4()
    service, task_manager = _service(model_id=None, client_id=own)

    await service.start_run(
        RunCreate(agent_id=uuid4(), description="fix the bug"),
        workspace_id=WORKSPACE,
        user_id=USER,
        provenance=_STARTED,
    )

    submitted = task_manager.submit_task.await_args.args[0]
    assert submitted.metadata[RUNNER_CLIENT_METADATA_KEY] == str(own)


@pytest.mark.asyncio
async def test_a_client_the_caller_may_not_use_is_refused_before_anything_is_stored(
    usable: set[UUID],
):
    service, task_manager = _service(model_id="gpt", client_id=None)

    with pytest.raises(InvalidRunnerClientError):
        await service.reserve_run(
            RunCreate(agent_id=uuid4(), description="fix the bug", runner_client_id=uuid4()),
            workspace_id=WORKSPACE,
            user_id=USER,
            provenance=_STARTED,
            task_id=uuid4(),
        )

    service.create_task.assert_not_awaited()
    task_manager.submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_reserved_run_keeps_the_named_client(usable: set[UUID]):
    runner = uuid4()
    usable.add(runner)
    service, _ = _service(model_id="gpt", client_id=None)

    task = await service.reserve_run(
        RunCreate(agent_id=uuid4(), description="fix the bug", runner_client_id=runner),
        workspace_id=WORKSPACE,
        user_id=USER,
        provenance=_STARTED,
        task_id=uuid4(),
    )

    assert task.metadata[RUNNER_CLIENT_METADATA_KEY] == str(runner)
