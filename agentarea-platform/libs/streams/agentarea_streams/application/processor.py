"""Run a processor's code over one event in the sandbox and write what it returns.

The code decides what the event means; the platform only runs it, keeps it to
its declared outputs and links each event it writes to the one it read:
``causation_id`` is the source event, ``correlation_id`` carries over, the
depth grows by one and is bounded like a forward's. Each written event's id is
``uuid5(processor, source event, position)``, so a redelivery writes nothing
twice. A copy keeps the source, sender and session of the event it came from,
as a forward does: sender admission reads them.

The code runs in ``prepare``, which the router calls with no database session
or connection open; the events are written afterwards in a new session. A
slow processor still holds up the other events of its stream's partition, up
to its timeout. A failure of the code (an exception, a timeout, a result that
is no list of events) is an ``error`` reaction, never retried. A sandbox that cannot run the
code raises ``ProcessorRuntimeUnavailableError``: the event is redelivered and,
past the delivery limit, dead-lettered with an ``error`` reaction.
"""

import logging
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import Verdict
from ..domain.errors import ProcessorFailedError, StreamNotFoundError
from ..domain.keys import processor_output_id
from ..domain.models import HandlerResult, StreamEvent, SubscriptionView
from ..domain.ports import CodeRunner, FinishReaction
from ..domain.processor import (
    MAX_RESULT_BYTES,
    TIMEOUT_SECONDS,
    ProcessorOutput,
    event_payload,
    harness_command,
    outputs_of,
    resolve_streams,
    sandbox_session,
)
from ..infrastructure.bus import StreamBus
from ..infrastructure.repository import StreamRepository
from .ingest import StreamIngest

logger = logging.getLogger(__name__)

NO_EVENTS_REASON = "process() wrote no events"


class ProcessorHandler:
    def __init__(self, settings: EventStreamSettings, bus: StreamBus, runner: CodeRunner):
        self._settings = settings
        self._bus = bus
        self._runner = runner

    async def handle(
        self, subscription: SubscriptionView, event: StreamEvent, session: AsyncSession
    ) -> HandlerResult:
        """Both parts at once; the router calls ``prepare`` first, with no session open."""
        finish = await self.prepare(subscription, event)
        return await finish(session)

    async def prepare(self, subscription: SubscriptionView, event: StreamEvent) -> FinishReaction:
        """Run the code in the sandbox; the returned step writes its events in a session."""
        depth = event.depth + 1
        if depth > self._settings.FORWARD_DEPTH:
            return _settled(
                _error(f"causation depth {depth} exceeds {self._settings.FORWARD_DEPTH}")
            )
        if subscription.stream_id in subscription.output_stream_ids:
            return _settled(_error("a processor never writes to its own input stream"))
        if not subscription.code:
            return _settled(_error("the processor has no code"))
        try:
            command = harness_command(subscription.code, event_payload(event))
            run = await self._runner.run(
                workspace_id=subscription.workspace_id,
                session=sandbox_session(subscription.id),
                command=command,
                timeout_seconds=TIMEOUT_SECONDS,
                max_output_bytes=MAX_RESULT_BYTES,
            )
            outputs = outputs_of(run)
        except ProcessorFailedError as failure:
            logger.info("Processor %s failed on event %s: %s", subscription.id, event.id, failure)
            return _settled(_error(str(failure)))

        async def finish(session: AsyncSession) -> HandlerResult:
            return await self._write(session, subscription, event, outputs, depth)

        return finish

    async def _write(
        self,
        session: AsyncSession,
        subscription: SubscriptionView,
        event: StreamEvent,
        outputs: list[ProcessorOutput],
        depth: int,
    ) -> HandlerResult:
        owner = UserContext(user_id=subscription.created_by, workspace_id=subscription.workspace_id)
        try:
            routed = resolve_streams(
                outputs,
                await StreamRepository(session, owner).names(subscription.output_stream_ids),
                subscription.stream_id,
            )
        except ProcessorFailedError as failure:
            logger.info("Processor %s failed on event %s: %s", subscription.id, event.id, failure)
            return _error(str(failure))
        if not routed:
            return HandlerResult(verdict=Verdict.SKIPPED, reason=NO_EVENTS_REASON)
        ingest = StreamIngest(session, owner, self._settings, self._bus)
        written: list[UUID] = []
        for index, (stream_id, output) in enumerate(routed):
            event_id = processor_output_id(subscription.id, event.id, index)
            try:
                await ingest.append(
                    stream_id,
                    IntegrationEvent(
                        type=output.kind,
                        source=f"processor:{subscription.id}",
                        subject=event.subject,
                        time=event.time,
                        correlation_id=event.correlation_id or str(event.id),
                        causation_id=str(event.id),
                        data=output.data,
                    ),
                    event_key=output.key or f"{event.id}:{index}",
                    depth=depth,
                    event_id=event_id,
                    source_id=event.source_id,
                    source_type=event.source_type,
                    session_key=event.session_key,
                    sender=event.sender,
                )
            except StreamNotFoundError:
                logger.info(
                    "Processor %s skips output %s, which no longer exists",
                    subscription.id,
                    stream_id,
                )
                continue
            written.append(event_id)
        return HandlerResult(verdict=Verdict.REACTED, derived_event_ids=written)


def _settled(result: HandlerResult) -> FinishReaction:
    async def finish(_session: AsyncSession) -> HandlerResult:
        return result

    return finish


def _error(reason: str) -> HandlerResult:
    return HandlerResult(verdict=Verdict.ERROR, reason=reason)
