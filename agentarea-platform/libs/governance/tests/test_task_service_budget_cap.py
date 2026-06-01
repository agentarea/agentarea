"""Unit tests for TaskService._enforce_budget_cap() and its invocation by creation entry points."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    PolicyDocument,
    PolicyValidationError,
)
from agentarea_governance.infrastructure.repository import (
    GovernancePolicyRepository,
    TaskPolicySnapshotRepository,
)
from agentarea_tasks.domain.exceptions import BudgetCapExceededError
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService


def _make_service(
    *,
    governance_policy_repository=None,
    task_policy_snapshot_repository=None,
    task_repository=None,
):
    """Build a TaskService with all external dependencies mocked."""
    mock_task_repo = task_repository or AsyncMock()

    mock_factory = MagicMock()
    # @audited decorator reads .session and .user_context off the factory.
    mock_factory.session = MagicMock()
    mock_factory.user_context = MagicMock()
    mock_factory.user_context.user_id = "user-123"
    mock_factory.user_context.workspace_id = "ws-test"

    mock_agent_repo = AsyncMock()
    mock_policy_repo = governance_policy_repository or AsyncMock()
    if governance_policy_repository is None:
        mock_policy_repo.get_chain.return_value = ([], [])
    mock_snapshot_repo = task_policy_snapshot_repository or AsyncMock()

    def create_repository(repo_cls):
        if repo_cls is TaskRepository:
            return mock_task_repo
        if repo_cls is GovernancePolicyRepository:
            return mock_policy_repo
        if repo_cls is TaskPolicySnapshotRepository:
            return mock_snapshot_repo
        return mock_agent_repo

    mock_factory.create_repository.side_effect = create_repository

    mock_event_broker = AsyncMock()
    mock_task_manager = AsyncMock()

    service = TaskService(mock_factory, mock_event_broker, mock_task_manager)
    service.task_repository = mock_task_repo
    return service


def _policy_repo_with_cap(cap):
    policy_repo = AsyncMock()
    policy_repo.get_chain.return_value = (
        ["policy-1"],
        [PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd=cap))],
    )
    return policy_repo


@pytest.fixture
def workspace_id():
    return "ws-" + str(uuid4())


@pytest.fixture
def mock_task_repo():
    return AsyncMock()


class TestEnforceBudgetCap:
    async def test_raises_budget_cap_exceeded_when_mtd_spend_equals_cap(
        self, workspace_id, mock_task_repo
    ):
        policy_repo = _policy_repo_with_cap("100.0")
        mock_task_repo.sum_spend_mtd.return_value = 100.0

        service = _make_service(
            governance_policy_repository=policy_repo, task_repository=mock_task_repo
        )

        with pytest.raises(BudgetCapExceededError) as exc_info:
            await service._enforce_budget_cap(workspace_id)

        err = exc_info.value
        assert err.workspace_id == workspace_id
        assert err.current_mtd_usd == 100.0
        assert err.cap_usd == 100.0

    async def test_raises_budget_cap_exceeded_when_mtd_spend_exceeds_cap(
        self, workspace_id, mock_task_repo
    ):
        policy_repo = _policy_repo_with_cap("50.0")
        mock_task_repo.sum_spend_mtd.return_value = 75.5

        service = _make_service(
            governance_policy_repository=policy_repo, task_repository=mock_task_repo
        )

        with pytest.raises(BudgetCapExceededError) as exc_info:
            await service._enforce_budget_cap(workspace_id)

        err = exc_info.value
        assert err.current_mtd_usd == 75.5
        assert err.cap_usd == 50.0

    async def test_no_op_when_no_governance_policy(self, workspace_id, mock_task_repo):
        service = _make_service(task_repository=mock_task_repo)

        await service._enforce_budget_cap(workspace_id)
        mock_task_repo.sum_spend_mtd.assert_not_called()

    async def test_no_op_when_workspace_id_is_none(self, mock_task_repo):
        service = _make_service(task_repository=mock_task_repo)

        await service._enforce_budget_cap(None)
        mock_task_repo.sum_spend_mtd.assert_not_called()

    async def test_no_op_when_workspace_id_is_empty_string(self, mock_task_repo):
        service = _make_service(task_repository=mock_task_repo)

        await service._enforce_budget_cap("")
        mock_task_repo.sum_spend_mtd.assert_not_called()

    async def test_no_error_raised_when_mtd_spend_below_cap(self, workspace_id, mock_task_repo):
        policy_repo = _policy_repo_with_cap("200.0")
        mock_task_repo.sum_spend_mtd.return_value = 99.99

        service = _make_service(
            governance_policy_repository=policy_repo, task_repository=mock_task_repo
        )

        await service._enforce_budget_cap(workspace_id)

    async def test_error_message_contains_workspace_and_spend_info(
        self, workspace_id, mock_task_repo
    ):
        policy_repo = _policy_repo_with_cap("10.0")
        mock_task_repo.sum_spend_mtd.return_value = 10.0

        service = _make_service(
            governance_policy_repository=policy_repo, task_repository=mock_task_repo
        )

        with pytest.raises(BudgetCapExceededError) as exc_info:
            await service._enforce_budget_cap(workspace_id)

        message = str(exc_info.value)
        assert workspace_id in message
        assert "10.00" in message


class TestCreationEntryPointsInvokeBudgetCap:
    async def test_create_task_with_policy_invokes_enforce_budget_cap(
        self, workspace_id, mock_task_repo
    ):
        service = _make_service(task_repository=mock_task_repo)

        agent_id = uuid4()

        with patch.object(
            service, "_enforce_budget_cap", new_callable=AsyncMock
        ) as mock_enforce, patch.object(
            service, "create_task", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = MagicMock()
            await service.create_task_with_policy(
                agent_id=agent_id,
                description="A test",
                workspace_id=workspace_id,
                user_id="user-123",
                title="Test task",
                query="do something",
            )

        mock_enforce.assert_awaited_once()
        assert mock_enforce.await_args.args[0] == workspace_id

    async def test_create_and_execute_task_with_workflow_invokes_enforce_budget_cap(
        self, workspace_id, mock_task_repo
    ):
        service = _make_service(task_repository=mock_task_repo)

        agent_id = uuid4()

        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        service.agent_repository = AsyncMock()
        service.agent_repository.get.return_value = mock_agent

        with patch.object(
            service, "_enforce_budget_cap", new_callable=AsyncMock
        ) as mock_enforce, patch.object(
            service, "create_task", new_callable=AsyncMock
        ) as mock_create, patch.object(
            service, "_try_route_to_active_workflow", new_callable=AsyncMock
        ) as mock_route, patch.object(
            service.task_manager, "submit_task", new_callable=AsyncMock
        ):
            mock_created = MagicMock()
            mock_created.id = uuid4()
            mock_created.status = "pending"
            mock_create.return_value = mock_created
            mock_route.return_value = None

            await service.create_and_execute_task_with_workflow(
                agent_id=agent_id,
                description="run a workflow",
                workspace_id=workspace_id,
                user_id="user-123",
            )

        mock_enforce.assert_awaited_once()
        assert mock_enforce.await_args.args[0] == workspace_id

    async def test_create_and_execute_task_with_workflow_budget_cap_blocks_execution(
        self, workspace_id, mock_task_repo
    ):
        """BudgetCapExceededError from _enforce_budget_cap propagates and blocks execution.

        Asserts agent fetch never runs — proving the cap check fires first.
        """
        policy_repo = _policy_repo_with_cap("5.0")
        mock_task_repo.sum_spend_mtd.return_value = 10.0

        service = _make_service(
            governance_policy_repository=policy_repo, task_repository=mock_task_repo
        )

        agent_id = uuid4()
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        service.agent_repository = AsyncMock()
        service.agent_repository.get.return_value = mock_agent

        with pytest.raises(BudgetCapExceededError):
            await service.create_and_execute_task_with_workflow(
                agent_id=agent_id,
                description="blocked task",
                workspace_id=workspace_id,
            )

        service.agent_repository.get.assert_not_called()

    async def test_snapshot_failure_blocks_workflow_dispatch(
        self, workspace_id, mock_task_repo
    ):
        snapshot_repo = AsyncMock()
        snapshot_repo.create_snapshot.side_effect = RuntimeError("snapshot write failed")
        service = _make_service(
            task_repository=mock_task_repo,
            task_policy_snapshot_repository=snapshot_repo,
        )

        agent_id = uuid4()
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        service.agent_repository = AsyncMock()
        service.agent_repository.get.return_value = mock_agent

        with patch.object(
            service, "create_task", new_callable=AsyncMock
        ) as mock_create, patch.object(
            service, "_try_route_to_active_workflow", new_callable=AsyncMock
        ) as mock_route, patch.object(
            service.task_manager, "submit_task", new_callable=AsyncMock
        ) as mock_submit:
            mock_created = MagicMock()
            mock_created.id = uuid4()
            mock_created.status = "pending"
            mock_create.return_value = mock_created
            mock_route.return_value = None

            with pytest.raises(RuntimeError, match="snapshot write failed"):
                await service.create_and_execute_task_with_workflow(
                    agent_id=agent_id,
                    description="run a workflow",
                    workspace_id=workspace_id,
                    user_id="user-123",
                )

        mock_submit.assert_not_awaited()

    async def test_loosening_task_policy_blocks_workflow_start(
        self, workspace_id, mock_task_repo
    ):
        policy_repo = _policy_repo_with_cap("100.00")
        service = _make_service(
            governance_policy_repository=policy_repo,
            task_repository=mock_task_repo,
        )

        agent_id = uuid4()

        with patch.object(
            service, "create_task", new_callable=AsyncMock
        ) as mock_create, patch.object(
            service.task_manager, "submit_task", new_callable=AsyncMock
        ) as mock_submit:
            with pytest.raises(PolicyValidationError):
                await service.create_and_execute_task_with_workflow(
                    agent_id=agent_id,
                    description="run a workflow",
                    workspace_id=workspace_id,
                    user_id="user-123",
                    task_policy=PolicyDocument(
                        budget=BudgetPolicy(monthly_spend_cap_usd="200.00")
                    ),
                )

        mock_create.assert_not_awaited()
        mock_submit.assert_not_awaited()
