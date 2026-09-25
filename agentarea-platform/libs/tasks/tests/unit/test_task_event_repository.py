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
from agentarea_tasks.infrastructure.repository import TaskEventRepository


def _capturing_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


class TestCreateEventPersistsMetadata:
    @pytest.mark.asyncio
    async def test_event_metadata_column_receives_the_event_metadata(self):
        session = _capturing_session()
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))
        event = TaskEvent(
            task_id=uuid4(),
            event_type="LLMCallCompleted",
            timestamp=datetime.now(UTC),
            data={},
            metadata={"tool": "search"},
            workspace_id="alice-ws",
            created_by="alice",
        )

        await repo.create_event(event)

        event_orm = session.add.call_args.args[0]
        assert event_orm.event_metadata == {"tool": "search"}

    @pytest.mark.asyncio
    async def test_metadata_kwarg_does_not_shadow_the_class_level_metaclass_attribute(self):
        """Regression guard: a `metadata=` kwarg must never reach the ORM constructor."""
        session = _capturing_session()
        repo = TaskEventRepository(session, UserContext(user_id="alice", workspace_id="alice-ws"))
        event = TaskEvent(
            task_id=uuid4(),
            event_type="LLMCallCompleted",
            timestamp=datetime.now(UTC),
            data={},
            metadata={"tool": "search"},
            workspace_id="alice-ws",
            created_by="alice",
        )

        await repo.create_event(event)

        event_orm = session.add.call_args.args[0]
        assert "metadata" not in event_orm.__dict__
