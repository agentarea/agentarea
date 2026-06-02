"""Durable inbound channel event consumer backed by Redis Streams.

Go event-service writes normalized channel events to an inbound stream. This
consumer claims them with a shared consumer group and creates trigger
executions. Messages are ACKed only after trigger execution succeeds.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from agentarea_common.broker import BrokerClient, BrokerMessage, DedupCache

if TYPE_CHECKING:
    from agentarea_common.events.broker import EventBroker

    WorkflowExecutor = Any

logger = logging.getLogger(__name__)


class InboundMessageStreamConsumer:
    """Consumes normalized inbound channel events from a durable stream."""

    def __init__(
        self,
        broker: BrokerClient,
        dedup: DedupCache,
        *,
        event_broker: EventBroker,
        workflow_executor: WorkflowExecutor | None = None,
        stream: str,
        group: str,
        dlq_stream: str,
        consumer_id: str = "c1",
        block_ms: int = 5000,
        batch_size: int = 10,
        max_delivery_attempts: int = 20,
    ) -> None:
        self._broker = broker
        self._dedup = dedup
        self._event_broker = event_broker
        self._workflow_executor = workflow_executor
        self._stream = stream
        self._group = group
        self._dlq_stream = dlq_stream
        self._consumer_id = consumer_id
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._max_delivery_attempts = max_delivery_attempts
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        await self._broker.ensure_group(self._stream, self._group, start="0")
        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(),
            name="inbound-message-stream-consumer",
        )
        logger.info(
            "InboundMessageStreamConsumer started (stream=%s group=%s consumer=%s)",
            self._stream,
            self._group,
            self._consumer_id,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("InboundMessageStreamConsumer stopped (stream=%s)", self._stream)

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                msgs = await self._broker.consume(
                    self._stream,
                    self._group,
                    self._consumer_id,
                    count=self._batch_size,
                    block_ms=self._block_ms,
                )
                for msg in msgs:
                    await self._handle(msg)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                logger.error(
                    "InboundMessageStreamConsumer loop error (retry in %.0fs): %s",
                    backoff,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _handle(self, msg: BrokerMessage) -> None:
        fields = msg.fields
        dedup_key = fields.get("dedup_key") or msg.id

        if msg.delivery_count > self._max_delivery_attempts:
            await self._dead_letter(
                msg,
                f"max delivery attempts ({msg.delivery_count}) exceeded",
            )
            return

        if not await self._dedup.claim(dedup_key):
            logger.debug("inbound dedup hit on %s, acking", dedup_key)
            await self._broker.ack(self._stream, self._group, msg.id)
            return

        try:
            trigger_id, trigger_data = self._parse_fields(fields)
        except ValueError as exc:
            await self._dead_letter(msg, str(exc))
            return

        try:
            await self._execute_trigger(trigger_id, trigger_data)
        except ValueError as exc:
            await self._dead_letter(msg, str(exc))
            return
        except Exception:
            logger.exception("inbound trigger execution failed for %s", trigger_id)
            await self._dedup.release(dedup_key)
            return

        await self._broker.ack(self._stream, self._group, msg.id)
        logger.info("Inbound trigger %s executed from stream message %s", trigger_id, msg.id)

    def _parse_fields(self, fields: dict[str, str]) -> tuple[str, dict[str, Any]]:
        trigger_id = fields.get("trigger_id")
        if not trigger_id:
            raise ValueError("missing trigger_id")

        event_raw = fields.get("event", "{}")
        origin_raw = fields.get("channel_origin", "{}")

        try:
            event = json.loads(event_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"bad event json: {exc}") from exc
        try:
            channel_origin = json.loads(origin_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"bad channel_origin json: {exc}") from exc

        if not isinstance(event, dict):
            raise ValueError("event must be a JSON object")
        if not isinstance(channel_origin, dict):
            raise ValueError("channel_origin must be a JSON object")

        return trigger_id, {"events": [event], "channel_origin": channel_origin}

    async def _dead_letter(self, msg: BrokerMessage, reason: str) -> None:
        dlq_fields = {**msg.fields, "fatal_reason": reason[:500]}
        try:
            await self._broker.submit(self._dlq_stream, dlq_fields)
        except Exception:
            logger.exception("failed to write inbound DLQ for %s", msg.id)
        await self._broker.ack(self._stream, self._group, msg.id)
        logger.error("inbound channel event DLQ'd: %s (reason=%s)", msg.id, reason)

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
            trigger_orm = await session.get(TriggerORM, UUID(trigger_id))
            if not trigger_orm:
                raise ValueError(f"trigger {trigger_id} not found")

            user_context = UserContext(
                user_id=str(trigger_orm.created_by),
                workspace_id=str(trigger_orm.workspace_id),
            )

            repository_factory = RepositoryFactory(session, user_context)
            task_repository = repository_factory.create_repository(TaskRepository)

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
