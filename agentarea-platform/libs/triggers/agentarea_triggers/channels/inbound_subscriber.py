"""Redis subscriber for inbound channel messages from Go event service.

Listens to `agentarea.channel.message.received` and calls trigger execution
logic to create and submit agent tasks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis

if TYPE_CHECKING:
    from agentarea_common.events.base import EventBroker
    from agentarea_common.workflow.base import WorkflowExecutor

logger = logging.getLogger(__name__)

INBOUND_CHANNEL = "agentarea.channel.message.received"


class InboundMessageSubscriber:
    """Subscribes to Redis for inbound channel messages and triggers task execution.

    The Go event service publishes messages here when Telegram (or other channels)
    receive new messages. This subscriber picks them up and calls
    TriggerService.execute_trigger() to create and run agent tasks.
    """

    def __init__(
        self,
        redis_url: str,
        event_broker: EventBroker,
        workflow_executor: WorkflowExecutor | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._event_broker = event_broker
        self._workflow_executor = workflow_executor
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="inbound-message-subscriber")
        logger.info("InboundMessageSubscriber started (channel=%s)", INBOUND_CHANNEL)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                # Expected during shutdown - task cancellation is normal
                pass
            self._task = None
        logger.info("InboundMessageSubscriber stopped")

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                await self._subscribe_and_dispatch()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                logger.error(
                    "InboundMessageSubscriber error (retrying in %.0fs): %s",
                    backoff,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _subscribe_and_dispatch(self) -> None:
        client: redis.Redis = redis.from_url(self._redis_url, decode_responses=True)
        pubsub = client.pubsub()

        try:
            await pubsub.subscribe(INBOUND_CHANNEL)
            logger.debug("subscribed to %s", INBOUND_CHANNEL)

            async for raw_message in pubsub.listen():
                if not self._running:
                    break
                if raw_message.get("type") != "message":
                    continue
                await self._handle_message(raw_message)
        finally:
            try:
                await pubsub.unsubscribe(INBOUND_CHANNEL)
                await pubsub.close()
            except Exception as exc:
                logger.debug("Pubsub cleanup error suppressed: %s", exc)
            try:
                await client.aclose()
            except Exception as exc:
                logger.debug("Redis client close error suppressed: %s", exc)

    async def _handle_message(self, raw_message: dict[str, Any]) -> None:
        try:
            payload: str = raw_message.get("data", "")
            if not payload:
                return

            msg = json.loads(payload)
            trigger_id = msg.get("trigger_id")
            event = msg.get("event", {})
            channel_origin = msg.get("channel_origin", {})

            if not trigger_id:
                logger.warning("Inbound message missing trigger_id, skipping")
                return

            logger.info(
                "Inbound message received for trigger %s (text=%s)",
                trigger_id,
                (event.get("text") or "")[:50],
            )

            trigger_data: dict[str, Any] = {
                "events": [event],
                "channel_origin": channel_origin,
            }

            await self._execute_trigger(trigger_id, trigger_data)

        except Exception:
            logger.exception("Failed to handle inbound channel message")

    async def _execute_trigger(self, trigger_id: str, trigger_data: dict[str, Any]) -> None:
        """Execute the trigger using TriggerService with a fresh DB session."""
        from uuid import UUID

        from agentarea_common.auth.context import UserContext
        from agentarea_common.base.repository_factory import RepositoryFactory
        from agentarea_common.config import get_database
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_tasks.task_service import TaskService
        from agentarea_tasks.temporal_task_manager import TemporalTaskManager

        from agentarea_triggers.infrastructure.orm import TriggerORM
        from agentarea_triggers.trigger_service import TriggerService

        database = get_database()
        async with database.async_session_factory() as session:
            # Resolve workspace context from trigger
            trigger_orm = await session.get(TriggerORM, UUID(trigger_id))
            if not trigger_orm:
                logger.error("Trigger %s not found, cannot execute", trigger_id)
                return

            user_context = UserContext(
                user_id=str(trigger_orm.created_by),
                workspace_id=str(trigger_orm.workspace_id),
            )

            repository_factory = RepositoryFactory(session, user_context)
            task_repository = repository_factory.create_repository(TaskRepository)

            # Wire task manager with the shared Temporal executor
            if self._workflow_executor is not None:
                task_manager = TemporalTaskManager.__new__(TemporalTaskManager)
                task_manager.task_repository = task_repository
                task_manager.temporal_executor = self._workflow_executor
            else:
                task_manager = TemporalTaskManager(task_repository=task_repository)

            task_service = TaskService(
                repository_factory=repository_factory,
                event_broker=self._event_broker,
                task_manager=task_manager,
            )

            trigger_service = TriggerService(
                repository_factory=repository_factory,
                event_broker=self._event_broker,
                task_service=task_service,
            )

            execution = await trigger_service.execute_trigger(UUID(trigger_id), trigger_data)

            if execution:
                logger.info(
                    "Trigger %s executed, task_id=%s",
                    trigger_id,
                    execution.task_id,
                )
