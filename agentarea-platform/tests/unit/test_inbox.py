"""Unit tests for inbox API endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.v1.inbox import (
    INBOX_STATUSES,
    get_inbox_count,
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

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=None,
            limit=100,
            offset=0,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert len(result) == 1
        assert result[0].status == "waiting_for_approval"
        assert result[0].agent_name == "Test Agent"
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

        result = await get_inbox_items(
            user_context=test_user_context,
            status="waiting_for_approval",
            agent_id=None,
            limit=100,
            offset=0,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert len(result) == 1
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

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=test_agent_id,
            limit=100,
            offset=0,
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

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=None,
            limit=100,
            offset=0,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_inbox_count(
        self, mock_task_service, test_user_context
    ):
        mock_task_service.task_repository.count_by_statuses.return_value = 5

        result = await get_inbox_count(
            user_context=test_user_context,
            task_service=mock_task_service,
        )

        assert result == {"count": 5}
        mock_task_service.task_repository.count_by_statuses.assert_called_once_with(
            statuses=INBOX_STATUSES,
        )

    @pytest.mark.asyncio
    async def test_get_inbox_count_zero(
        self, mock_task_service, test_user_context
    ):
        mock_task_service.task_repository.count_by_statuses.return_value = 0

        result = await get_inbox_count(
            user_context=test_user_context,
            task_service=mock_task_service,
        )

        assert result == {"count": 0}

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

        result = await get_inbox_items(
            user_context=test_user_context,
            status=None,
            agent_id=None,
            limit=100,
            offset=0,
            agent_service=mock_agent_service,
            task_service=mock_task_service,
        )

        assert len(result) == 1
        assert result[0].agent_name == "Unknown"
