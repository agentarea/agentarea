"""Unit tests for inbox API endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.v1.inbox import (
    INBOX_STATUSES,
    get_inbox_items,
)
from agentarea_tasks.task_service import TaskService


class TestInboxEndpoints:
    """Test cases for inbox API endpoints."""

    @pytest.fixture
    def mock_agent_service(self):
        service = AsyncMock(spec=AgentService)
        return service

    @pytest.fixture
    def mock_task_service(self):
        service = AsyncMock(spec=TaskService)
        service.task_repository = AsyncMock()
        return service

    @pytest.fixture
    def test_agent_id(self):
        return uuid4()

    @pytest.fixture
    def mock_agents(self, test_agent_id):
        agent = MagicMock()
        agent.id = test_agent_id
        agent.name = "Test Agent"
        return [agent]

    @pytest.fixture
    def mock_task_domain(self, test_agent_id):
        """Create a mock task domain object."""
        task = MagicMock()
        task.id = uuid4()
        task.agent_id = test_agent_id
        task.description = "Test task"
        task.parameters = {}
        task.status = "waiting_for_approval"
        task.result = None
        task.created_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        task.execution_id = "wf-123"
        return task

    @pytest.mark.asyncio
    async def test_get_inbox_items_returns_actionable_tasks(
        self, mock_agent_service, mock_task_service, mock_agents, mock_task_domain, test_user_context
    ):
        mock_agent_service.list.return_value = mock_agents
        mock_task_service.task_repository.list_by_statuses.return_value = [mock_task_domain]
        mock_task_service.task_repository.count_by_statuses.return_value = 1

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=None,
            page=1,
            page_size=100,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert len(result.items) == 1
        assert result.total == 1
        assert result.page == 1
        assert result.page_size == 100
        assert result.items[0].status == "waiting_for_approval"
        assert result.items[0].agent_name == "Test Agent"
        mock_task_service.task_repository.list_by_statuses.assert_called_once_with(
            statuses=INBOX_STATUSES,
            agent_id=None,
            limit=100,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_get_inbox_items_with_status_filter(
        self, mock_agent_service, mock_task_service, mock_agents, mock_task_domain, test_user_context
    ):
        mock_agent_service.list.return_value = mock_agents
        mock_task_service.task_repository.list_by_statuses.return_value = [mock_task_domain]
        mock_task_service.task_repository.count_by_statuses.return_value = 1

        result = await get_inbox_items(
            user_context=test_user_context,
            status="waiting_for_approval",
            agent_id=None,
            page=1,
            page_size=100,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert len(result.items) == 1
        mock_task_service.task_repository.list_by_statuses.assert_called_once_with(
            statuses=["waiting_for_approval"],
            agent_id=None,
            limit=100,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_get_inbox_items_with_agent_filter(
        self, mock_agent_service, mock_task_service, mock_agents, mock_task_domain, test_user_context, test_agent_id
    ):
        mock_agent_service.list.return_value = mock_agents
        mock_task_service.task_repository.list_by_statuses.return_value = [mock_task_domain]
        mock_task_service.task_repository.count_by_statuses.return_value = 1

        await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=test_agent_id,
            page=1,
            page_size=100,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        mock_task_service.task_repository.list_by_statuses.assert_called_once_with(
            statuses=INBOX_STATUSES,
            agent_id=test_agent_id,
            limit=100,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_get_inbox_items_empty(
        self, mock_agent_service, mock_task_service, mock_agents, test_user_context
    ):
        mock_agent_service.list.return_value = mock_agents
        mock_task_service.task_repository.list_by_statuses.return_value = []
        mock_task_service.task_repository.count_by_statuses.return_value = 0

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=None,
            page=1,
            page_size=100,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert len(result.items) == 0
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_get_inbox_total_for_badge(
        self, mock_agent_service, mock_task_service, mock_agents, mock_task_domain, test_user_context
    ):
        """Total field serves as badge count — no separate endpoint needed."""
        mock_agent_service.list.return_value = mock_agents
        mock_task_service.task_repository.list_by_statuses.return_value = [mock_task_domain]
        mock_task_service.task_repository.count_by_statuses.return_value = 42

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=None,
            page=1,
            page_size=100,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert result.total == 42

    @pytest.mark.asyncio
    async def test_get_inbox_pagination(
        self, mock_agent_service, mock_task_service, mock_agents, test_user_context
    ):
        mock_agent_service.list.return_value = mock_agents
        mock_task_service.task_repository.list_by_statuses.return_value = []
        mock_task_service.task_repository.count_by_statuses.return_value = 50

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=None,
            page=3,
            page_size=10,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert result.page == 3
        assert result.page_size == 10
        mock_task_service.task_repository.list_by_statuses.assert_called_once_with(
            statuses=INBOX_STATUSES,
            agent_id=None,
            limit=10,
            offset=20,  # (page 3 - 1) * 10
        )

    @pytest.mark.asyncio
    async def test_inbox_statuses_include_all_expected(self):
        assert "waiting_for_approval" in INBOX_STATUSES
        assert "completed" in INBOX_STATUSES
        assert "failed" in INBOX_STATUSES

    @pytest.mark.asyncio
    async def test_get_inbox_items_unknown_agent(
        self, mock_agent_service, mock_task_service, mock_task_domain, test_user_context
    ):
        """Tasks from deleted/unknown agents should show 'Unknown' agent name."""
        mock_agent_service.list.return_value = []  # No agents
        mock_task_service.task_repository.list_by_statuses.return_value = [mock_task_domain]
        mock_task_service.task_repository.count_by_statuses.return_value = 1

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=None,
            page=1,
            page_size=100,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert len(result.items) == 1
        assert result.items[0].agent_name == "Unknown"
