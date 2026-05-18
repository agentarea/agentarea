"""Unit tests for inbox API endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_api.api.v1.inbox import (
    INBOX_STATUSES,
    STATUS_ALIASES,
    get_inbox_items,
)
from agentarea_tasks.infrastructure.repository import TaskRepository


class TestInboxEndpoints:
    """Test cases for inbox API endpoints."""

    @pytest.fixture
    def mock_task_repo(self):
        return AsyncMock(spec=TaskRepository)

    @pytest.fixture
    def mock_agent_repo(self):
        return AsyncMock(spec=AgentRepository)

    @pytest.fixture
    def mock_repository_factory(self, mock_task_repo, mock_agent_repo):
        factory = MagicMock()

        def _create(cls):
            if cls is TaskRepository:
                return mock_task_repo
            if cls is AgentRepository:
                return mock_agent_repo
            raise AssertionError(f"Unexpected repository: {cls}")

        factory.create_repository.side_effect = _create
        return factory

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
        self,
        mock_repository_factory,
        mock_task_repo,
        mock_agent_repo,
        mock_agents,
        mock_task_domain,
        test_user_context,
    ):
        mock_agent_repo.list_all.return_value = mock_agents
        mock_task_repo.list_by_statuses.return_value = [mock_task_domain]
        mock_task_repo.count_by_statuses.return_value = 1

        result = await get_inbox_items(
            user_context=test_user_context,
            repository_factory=mock_repository_factory,
            status=None,
            agent_id=None,
            page=1,
            page_size=100,
        )

        assert len(result.items) == 1
        assert result.total == 1
        assert result.items[0].status == "waiting_for_approval"
        assert result.items[0].agent_name == "Test Agent"
        mock_task_repo.list_by_statuses.assert_called_once_with(
            statuses=INBOX_STATUSES,
            agent_id=None,
            limit=100,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_get_inbox_items_with_status_filter(
        self,
        mock_repository_factory,
        mock_task_repo,
        mock_agent_repo,
        mock_agents,
        mock_task_domain,
        test_user_context,
    ):
        mock_agent_repo.list_all.return_value = mock_agents
        mock_task_repo.list_by_statuses.return_value = [mock_task_domain]
        mock_task_repo.count_by_statuses.return_value = 1

        await get_inbox_items(
            user_context=test_user_context,
            repository_factory=mock_repository_factory,
            status="waiting_for_approval",
            agent_id=None,
            page=1,
            page_size=100,
        )

        mock_task_repo.list_by_statuses.assert_called_once_with(
            statuses=["waiting_for_approval"],
            agent_id=None,
            limit=100,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_get_inbox_items_pending_alias_maps_to_waiting_for_approval(
        self,
        mock_repository_factory,
        mock_task_repo,
        mock_agent_repo,
        mock_agents,
        test_user_context,
    ):
        """Frontend filter value 'pending' must resolve to 'waiting_for_approval'."""
        mock_agent_repo.list_all.return_value = mock_agents
        mock_task_repo.list_by_statuses.return_value = []
        mock_task_repo.count_by_statuses.return_value = 0

        await get_inbox_items(
            user_context=test_user_context,
            repository_factory=mock_repository_factory,
            status="pending",
            agent_id=None,
            page=1,
            page_size=100,
        )

        assert STATUS_ALIASES["pending"] == "waiting_for_approval"
        mock_task_repo.list_by_statuses.assert_called_once_with(
            statuses=["waiting_for_approval"],
            agent_id=None,
            limit=100,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_get_inbox_items_with_agent_filter(
        self,
        mock_repository_factory,
        mock_task_repo,
        mock_agent_repo,
        mock_agents,
        mock_task_domain,
        test_user_context,
        test_agent_id,
    ):
        mock_agent_repo.list_all.return_value = mock_agents
        mock_task_repo.list_by_statuses.return_value = [mock_task_domain]
        mock_task_repo.count_by_statuses.return_value = 1

        await get_inbox_items(
            user_context=test_user_context,
            repository_factory=mock_repository_factory,
            status=None,
            agent_id=test_agent_id,
            page=1,
            page_size=100,
        )

        mock_task_repo.list_by_statuses.assert_called_once_with(
            statuses=INBOX_STATUSES,
            agent_id=test_agent_id,
            limit=100,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_get_inbox_items_empty(
        self,
        mock_repository_factory,
        mock_task_repo,
        mock_agent_repo,
        mock_agents,
        test_user_context,
    ):
        mock_agent_repo.list_all.return_value = mock_agents
        mock_task_repo.list_by_statuses.return_value = []
        mock_task_repo.count_by_statuses.return_value = 0

        result = await get_inbox_items(
            user_context=test_user_context,
            repository_factory=mock_repository_factory,
            status=None,
            agent_id=None,
            page=1,
            page_size=100,
        )

        assert len(result.items) == 0
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_get_inbox_total_for_badge(
        self,
        mock_repository_factory,
        mock_task_repo,
        mock_agent_repo,
        mock_agents,
        mock_task_domain,
        test_user_context,
    ):
        """Total field serves as badge count — no separate endpoint needed."""
        mock_agent_repo.list_all.return_value = mock_agents
        mock_task_repo.list_by_statuses.return_value = [mock_task_domain]
        mock_task_repo.count_by_statuses.return_value = 42

        result = await get_inbox_items(
            user_context=test_user_context,
            repository_factory=mock_repository_factory,
            status=None,
            agent_id=None,
            page=1,
            page_size=100,
        )

        assert result.total == 42

    @pytest.mark.asyncio
    async def test_get_inbox_pagination(
        self,
        mock_repository_factory,
        mock_task_repo,
        mock_agent_repo,
        mock_agents,
        test_user_context,
    ):
        mock_agent_repo.list_all.return_value = mock_agents
        mock_task_repo.list_by_statuses.return_value = []
        mock_task_repo.count_by_statuses.return_value = 50

        result = await get_inbox_items(
            user_context=test_user_context,
            repository_factory=mock_repository_factory,
            status=None,
            agent_id=None,
            page=3,
            page_size=10,
        )

        assert result.page == 3
        assert result.page_size == 10
        mock_task_repo.list_by_statuses.assert_called_once_with(
            statuses=INBOX_STATUSES,
            agent_id=None,
            limit=10,
            offset=20,
        )

    @pytest.mark.asyncio
    async def test_inbox_statuses_include_all_expected(self):
        assert "waiting_for_approval" in INBOX_STATUSES
        assert "completed" in INBOX_STATUSES
        assert "failed" in INBOX_STATUSES

    @pytest.mark.asyncio
    async def test_get_inbox_items_unknown_agent(
        self,
        mock_repository_factory,
        mock_task_repo,
        mock_agent_repo,
        mock_task_domain,
        test_user_context,
    ):
        """Tasks from deleted/unknown agents should show 'Unknown' agent name."""
        mock_agent_repo.list_all.return_value = []
        mock_task_repo.list_by_statuses.return_value = [mock_task_domain]
        mock_task_repo.count_by_statuses.return_value = 1

        result = await get_inbox_items(
            user_context=test_user_context,
            repository_factory=mock_repository_factory,
            status=None,
            agent_id=None,
            page=1,
            page_size=100,
        )

        assert len(result.items) == 1
        assert result.items[0].agent_name == "Unknown"
