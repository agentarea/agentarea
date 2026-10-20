"""A task's feed must never be readable across workspaces.

The feed is the task log (``task_conversation_entries``): message content, tool
arguments and results. A query filtered on ``task_id`` alone discloses the full
transcript of any task in any workspace, so these tests pin the workspace
predicate onto every statement the feed reader issues, including the count.

The log uses JSONB columns, which SQLite cannot compile, so this asserts on the
emitted SQL rather than round-tripping through an in-memory database.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.task_log import TaskFeedReader


def _capturing_session() -> MagicMock:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=0)
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


def _sql(statement) -> str:
    return str(statement.compile())


class TestFeedPageIsWorkspaceScoped:
    @pytest.mark.asyncio
    async def test_page_query_filters_by_workspace(self):
        session = _capturing_session()
        repo = TaskFeedReader(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        await repo.page(uuid4(), event_type=None, limit=50, offset=0)

        sql = _sql(session.execute.await_args.args[0])
        assert "task_conversation_entries.workspace_id" in sql
        assert "task_conversation_entries.task_id" in sql

    @pytest.mark.asyncio
    async def test_count_query_filters_by_workspace(self):
        """The total drives has_next; an unscoped count leaks the size of foreign tasks."""
        session = _capturing_session()
        repo = TaskFeedReader(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        await repo.page(uuid4(), event_type=None, limit=50, offset=0)

        sql = _sql(session.scalar.await_args.args[0])
        assert "task_conversation_entries.workspace_id" in sql

    @pytest.mark.asyncio
    async def test_event_type_filter_does_not_drop_the_workspace_predicate(self):
        session = _capturing_session()
        repo = TaskFeedReader(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        await repo.page(uuid4(), event_type="llm.call.completed", limit=50, offset=0)

        sql = _sql(session.execute.await_args.args[0])
        assert "task_conversation_entries.workspace_id" in sql
        assert "task_conversation_entries.name" in sql

    @pytest.mark.asyncio
    async def test_membership_does_not_widen_active_workspace_scope(self):
        session = _capturing_session()
        context = UserContext(
            user_id="alice",
            workspace_id="alice-ws",
            accessible_workspaces=["alice-ws", "shared-ws"],
        )
        repo = TaskFeedReader(session, context)

        await repo.page(uuid4(), event_type=None, limit=50, offset=0)

        sql = _sql(session.execute.await_args.args[0])
        assert "task_conversation_entries.workspace_id =" in sql
        assert "task_conversation_entries.workspace_id IN" not in sql

    @pytest.mark.asyncio
    async def test_returns_events_and_total(self):
        session = _capturing_session()
        session.scalar = AsyncMock(return_value=7)
        repo = TaskFeedReader(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        events, total = await repo.page(uuid4(), event_type=None, limit=2, offset=4)

        assert events == []
        assert total == 7
