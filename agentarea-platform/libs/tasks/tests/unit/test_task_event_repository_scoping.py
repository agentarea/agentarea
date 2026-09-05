"""`task_events` must never be readable across workspaces.

The event payload carries message content, tool arguments and tool results, so a
query filtered on ``task_id`` alone discloses the full transcript of any task in
any workspace. These tests pin the workspace predicate onto every statement the
repository issues, including the pagination count.

TaskEventORM uses JSONB columns, which SQLite cannot compile, so this asserts on
the emitted SQL rather than round-tripping through an in-memory database.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.repository import TaskEventRepository


def _capturing_session() -> MagicMock:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=0)
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


def _sql(statement) -> str:
    return str(statement.compile())


class TestListForTaskIsWorkspaceScoped:
    @pytest.mark.asyncio
    async def test_page_query_filters_by_workspace(self):
        session = _capturing_session()
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        await repo.list_for_task(uuid4())

        sql = _sql(session.execute.await_args.args[0])
        assert "task_events.workspace_id" in sql
        assert "task_events.task_id" in sql

    @pytest.mark.asyncio
    async def test_count_query_filters_by_workspace(self):
        """The total drives has_next; an unscoped count leaks the size of foreign tasks."""
        session = _capturing_session()
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        await repo.list_for_task(uuid4())

        sql = _sql(session.scalar.await_args.args[0])
        assert "task_events.workspace_id" in sql

    @pytest.mark.asyncio
    async def test_event_type_filter_does_not_drop_the_workspace_predicate(self):
        session = _capturing_session()
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        await repo.list_for_task(uuid4(), event_type="LLMCallCompleted")

        sql = _sql(session.execute.await_args.args[0])
        assert "task_events.workspace_id" in sql
        assert "task_events.event_type" in sql

    @pytest.mark.asyncio
    async def test_membership_does_not_widen_active_workspace_scope(self):
        session = _capturing_session()
        context = UserContext(
            user_id="alice",
            workspace_id="alice-ws",
            accessible_workspaces=["alice-ws", "shared-ws"],
        )
        repo = TaskEventRepository(session, context)

        await repo.list_for_task(uuid4())

        sql = _sql(session.execute.await_args.args[0])
        assert "task_events.workspace_id =" in sql
        assert "task_events.workspace_id IN" not in sql

    @pytest.mark.asyncio
    async def test_returns_events_and_total(self):
        session = _capturing_session()
        session.scalar = AsyncMock(return_value=7)
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        events, total = await repo.list_for_task(uuid4(), limit=2, offset=4)

        assert events == []
        assert total == 7
