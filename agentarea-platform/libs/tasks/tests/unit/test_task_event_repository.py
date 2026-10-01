"""`TaskEventRepository.create_event` must persist the event's metadata.

`TaskEventORM` declares its metadata column as `event_metadata` (never the bare
`metadata`, which SQLAlchemy's declarative base reserves for the class's own
`MetaData` object). Passing `metadata=` into the ORM constructor does not raise
and does not populate `event_metadata`: it silently sets an instance attribute
that shadows the class-level `MetaData`, and the actual column is left with its
default `{}` at flush time. This pins the fix in place.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.models import TaskEvent
from agentarea_tasks.infrastructure.orm import TaskEventORM
from agentarea_tasks.infrastructure.repository import TaskEventRepository
from sqlalchemy.dialects import postgresql


def _capturing_session(event: TaskEvent) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock(
        return_value=TaskEventORM(
            id=event.id,
            task_id=event.task_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            data=event.data,
            event_metadata=event.metadata,
            workspace_id=event.workspace_id,
            created_by=event.created_by,
        )
    )
    return session


def _inserted_values(session: MagicMock) -> dict:
    statement = session.execute.call_args.args[0]
    return statement.compile(dialect=postgresql.dialect()).params


class TestCreateEventPersistsMetadata:
    @pytest.mark.asyncio
    async def test_event_metadata_column_receives_the_event_metadata(self):
        event = TaskEvent(
            task_id=uuid4(),
            event_type="LLMCallCompleted",
            timestamp=datetime.now(UTC),
            data={},
            metadata={"tool": "search"},
            workspace_id="alice-ws",
            created_by="alice",
        )
        session = _capturing_session(event)
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        stored = await repo.create_event(event)

        assert _inserted_values(session)["event_metadata"] == {"tool": "search"}
        assert stored.metadata == {"tool": "search"}

    @pytest.mark.asyncio
    async def test_metadata_kwarg_does_not_shadow_the_class_level_metaclass_attribute(self):
        """Regression guard: a `metadata=` kwarg must never reach the insert."""
        event = TaskEvent(
            task_id=uuid4(),
            event_type="LLMCallCompleted",
            timestamp=datetime.now(UTC),
            data={},
            metadata={"tool": "search"},
            workspace_id="alice-ws",
            created_by="alice",
        )
        session = _capturing_session(event)
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        await repo.create_event(event)

        assert "metadata" not in _inserted_values(session)

    @pytest.mark.asyncio
    async def test_an_event_for_another_workspace_is_refused_before_writing(self):
        event = TaskEvent(
            task_id=uuid4(),
            event_type="tool.result",
            timestamp=datetime.now(UTC),
            data={},
            workspace_id="mallory-ws",
            created_by="alice",
        )
        session = _capturing_session(event)
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))

        with pytest.raises(ValueError, match="belongs to workspace"):
            await repo.create_event(event)

        session.execute.assert_not_awaited()
