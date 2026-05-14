"""Unit tests for TaskService._enforce_budget_cap() and its invocation by creation entry points."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_tasks.domain.exceptions import BudgetCapExceededError
from agentarea_tasks.task_service import TaskService


def _make_service(
    *,
    workspace_settings_repository=None,
    task_repository=None,
    inject_wsr=True,
):
    """Build a TaskService with all external dependencies mocked.

    When ``inject_wsr=False`` the workspaces import is patched to ImportError
    so the constructor leaves ``self.workspace_settings_repository = None``.
    """
    mock_task_repo = task_repository or AsyncMock()

    mock_factory = MagicMock()
    # @audited decorator reads .session and .user_context off the factory.
    mock_factory.session = MagicMock()
    mock_factory.user_context = MagicMock()

    mock_agent_repo = AsyncMock()

    if inject_wsr:
        mock_factory.create_repository.side_effect = [
            mock_task_repo,
            mock_agent_repo,
            workspace_settings_repository or AsyncMock(),
        ]
    else:
        mock_factory.create_repository.side_effect = [mock_task_repo, mock_agent_repo]

    mock_event_broker = AsyncMock()
    mock_task_manager = AsyncMock()

    if inject_wsr:
        service = TaskService(mock_factory, mock_event_broker, mock_task_manager)
    else:
        with patch.dict(
            "sys.modules",
            {
                "agentarea_workspaces": None,
                "agentarea_workspaces.infrastructure": None,
                "agentarea_workspaces.infrastructure.repository": None,
            },
        ):
            service = TaskService(mock_factory, mock_event_broker, mock_task_manager)

    service.task_repository = mock_task_repo
    return service


@pytest.fixture
def workspace_id():
    return "ws-" + str(uuid4())


@pytest.fixture
def mock_wsr():
    return AsyncMock()


@pytest.fixture
def mock_task_repo():
    return AsyncMock()


class TestEnforceBudgetCap:
    async def test_raises_budget_cap_exceeded_when_mtd_spend_equals_cap(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        settings = MagicMock()
        settings.monthly_cap_usd = 100.0
        mock_wsr.get.return_value = settings
        mock_task_repo.sum_spend_mtd.return_value = 100.0

        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        with pytest.raises(BudgetCapExceededError) as exc_info:
            await service._enforce_budget_cap(workspace_id)

        err = exc_info.value
        assert err.workspace_id == workspace_id
        assert err.current_mtd_usd == 100.0
        assert err.cap_usd == 100.0

    async def test_raises_budget_cap_exceeded_when_mtd_spend_exceeds_cap(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        settings = MagicMock()
        settings.monthly_cap_usd = 50.0
        mock_wsr.get.return_value = settings
        mock_task_repo.sum_spend_mtd.return_value = 75.5

        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        with pytest.raises(BudgetCapExceededError) as exc_info:
            await service._enforce_budget_cap(workspace_id)

        err = exc_info.value
        assert err.current_mtd_usd == 75.5
        assert err.cap_usd == 50.0

    async def test_no_op_when_workspace_settings_row_absent(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        mock_wsr.get.return_value = None

        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        await service._enforce_budget_cap(workspace_id)
        mock_task_repo.sum_spend_mtd.assert_not_called()

    async def test_no_op_when_monthly_cap_usd_is_none(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        settings = MagicMock()
        settings.monthly_cap_usd = None
        mock_wsr.get.return_value = settings

        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        await service._enforce_budget_cap(workspace_id)
        mock_task_repo.sum_spend_mtd.assert_not_called()

    async def test_no_op_when_workspace_id_is_none(self, mock_wsr, mock_task_repo):
        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        await service._enforce_budget_cap(None)

        mock_wsr.get.assert_not_called()
        mock_task_repo.sum_spend_mtd.assert_not_called()

    async def test_no_op_when_workspace_id_is_empty_string(self, mock_wsr, mock_task_repo):
        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        await service._enforce_budget_cap("")
        mock_wsr.get.assert_not_called()

    async def test_no_op_when_workspace_settings_repository_is_none(
        self, workspace_id, mock_task_repo
    ):
        service = _make_service(inject_wsr=False, task_repository=mock_task_repo)
        assert service.workspace_settings_repository is None

        await service._enforce_budget_cap(workspace_id)
        mock_task_repo.sum_spend_mtd.assert_not_called()

    async def test_no_error_raised_when_mtd_spend_below_cap(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        settings = MagicMock()
        settings.monthly_cap_usd = 200.0
        mock_wsr.get.return_value = settings
        mock_task_repo.sum_spend_mtd.return_value = 99.99

        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        await service._enforce_budget_cap(workspace_id)

    async def test_error_message_contains_workspace_and_spend_info(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        settings = MagicMock()
        settings.monthly_cap_usd = 10.0
        mock_wsr.get.return_value = settings
        mock_task_repo.sum_spend_mtd.return_value = 10.0

        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        with pytest.raises(BudgetCapExceededError) as exc_info:
            await service._enforce_budget_cap(workspace_id)

        message = str(exc_info.value)
        assert workspace_id in message
        assert "10.00" in message


class TestCreationEntryPointsInvokeBudgetCap:
    async def test_create_task_from_params_invokes_enforce_budget_cap(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

        agent_id = uuid4()

        with patch.object(
            service, "_enforce_budget_cap", new_callable=AsyncMock
        ) as mock_enforce, patch.object(
            service, "create_task", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = MagicMock()
            await service.create_task_from_params(
                title="Test task",
                description="A test",
                query="do something",
                user_id="user-123",
                agent_id=agent_id,
                workspace_id=workspace_id,
            )

        mock_enforce.assert_awaited_once_with(workspace_id)

    async def test_create_and_execute_task_with_workflow_invokes_enforce_budget_cap(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
        )

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

        mock_enforce.assert_awaited_once_with(workspace_id)

    async def test_create_and_execute_task_with_workflow_budget_cap_blocks_execution(
        self, workspace_id, mock_wsr, mock_task_repo
    ):
        """BudgetCapExceededError from _enforce_budget_cap propagates and blocks execution.

        Asserts agent fetch never runs — proving the cap check fires first.
        """
        settings = MagicMock()
        settings.monthly_cap_usd = 5.0
        mock_wsr.get.return_value = settings
        mock_task_repo.sum_spend_mtd.return_value = 10.0

        service = _make_service(
            workspace_settings_repository=mock_wsr, task_repository=mock_task_repo
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
