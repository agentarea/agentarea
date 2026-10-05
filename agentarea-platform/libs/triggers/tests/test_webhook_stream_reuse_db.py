"""Re-creating a deleted webhook trigger under its name and webhook id takes over its stream.

Deleting a webhook trigger keeps its stream for the history, and the stream's
name is unique per workspace, so the re-created trigger lands on that name.
The unique constraint and the cascade from trigger to subscription exist only
in the migrated schema. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import PermissionService
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.di.container import get_container
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.infrastructure.journal_repository import StreamJournal
from agentarea_streams.infrastructure.repository import StreamSourceRepository
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import TriggerCreate
from agentarea_triggers.logging_utils import TriggerValidationError
from agentarea_triggers.trigger_service import TriggerService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


class _Writers:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    async def check(self, user_id: str, permission: str, resource_type: str, resource_id: str):
        return self.allowed


@asynccontextmanager
async def _service(allowed: bool = True) -> AsyncIterator[tuple[TriggerService, AsyncSession]]:
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    container = get_container()
    container.register_singleton(PermissionService, _Writers(allowed))
    try:
        async with maker() as session:
            with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
                service = TriggerService(
                    repository_factory=RepositoryFactory(session, ctx), event_broker=AsyncMock()
                )
                service._validate_agent_exists = AsyncMock()  # type: ignore[method-assign]
                yield service, session
    finally:
        container.clear()
        await engine.dispose()


def _webhook(service: TriggerService, name: str, webhook_id: str) -> TriggerCreate:
    return TriggerCreate(
        name=name,
        agent_id=uuid4(),
        trigger_type=TriggerType.WEBHOOK,
        created_by="u",
        workspace_id=service.repository_factory.user_context.workspace_id,
        webhook_id=webhook_id,
        webhook_type="github",
        event_types=["push"],
        task_parameters={"text": "Summarise the push"},
    )


async def test_the_recreated_trigger_continues_its_stream_after_the_events_already_there():
    async with _service() as (service, session):
        webhook_id = f"wh{uuid4().hex}"
        first = await service.create_trigger(_webhook(service, "GitHub", webhook_id))
        stream_id = (await service.stream_service.trigger_bindings([first.id]))[first.id].stream_id
        journal = StreamJournal(
            session, service.repository_factory.user_context, EventStreamSettings()
        )
        before = await journal.append(
            stream_id, IntegrationEvent(type="push", source="webhook:github"), event_key="d-1"
        )
        await session.commit()

        assert await service.delete_trigger(first.id)
        await session.commit()
        again = await service.create_trigger(_webhook(service, "GitHub", webhook_id))
        await session.commit()

        binding = (await service.stream_service.trigger_bindings([again.id]))[again.id]
        assert binding.stream_id == stream_id
        assert binding.webhook_id == webhook_id
        subscription = await service.stream_service.trigger_subscription(again.id)
        assert subscription is not None
        assert subscription.cursor_sequence == before.sequence


async def test_a_left_stream_the_creator_may_not_write_to_is_refused_by_name():
    async with _service(allowed=False) as (service, session):
        webhook_id = f"wh{uuid4().hex}"
        first = await service.create_trigger(_webhook(service, "GitHub", webhook_id))
        assert await service.delete_trigger(first.id)
        await session.commit()

        with pytest.raises(TriggerValidationError, match=f"GitHub \\({webhook_id}\\)"):
            await service.create_trigger(_webhook(service, "GitHub", webhook_id))


async def test_a_stream_another_source_feeds_is_never_taken_over():
    async with _service() as (service, session):
        webhook_id = f"wh{uuid4().hex}"
        name = f"GitHub ({webhook_id})"
        custom = await service.stream_service.create_stream(
            name=name, description="", retention_days=7
        )
        await StreamSourceRepository(
            session, service.repository_factory.user_context
        ).add_webhook_source(
            stream_id=custom.id,
            webhook_id=f"wh{uuid4().hex}",
            webhook_type="generic",
            allowed_methods=["POST"],
            validation_rules={},
            webhook_config=None,
            credential_key=uuid4(),
        )
        await session.commit()

        with pytest.raises(TriggerValidationError, match="another source feeds it"):
            await service.create_trigger(_webhook(service, "GitHub", webhook_id))
