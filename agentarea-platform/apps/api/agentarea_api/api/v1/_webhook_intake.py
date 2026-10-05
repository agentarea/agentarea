"""Public webhook intake: find the source, verify and parse, record, answer 202."""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config import Settings
from agentarea_common.events.broker import EventBroker
from agentarea_streams.domain import (
    PayloadTooLargeError,
    StreamError,
    StreamQuotaExceededError,
)
from agentarea_streams.domain.ports import StreamWaker
from agentarea_streams.infrastructure.journal import StreamJournal
from agentarea_streams.infrastructure.repository import find_webhook_source
from agentarea_triggers.channels.secret_reader import SecretReader
from agentarea_triggers.webhook_intake import JournalAppendCallback, spec_from_source
from agentarea_triggers.webhook_manager import DefaultWebhookManager
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _refused(error: StreamError) -> dict[str, Any]:
    if isinstance(error, StreamQuotaExceededError):
        status = 429
    elif isinstance(error, PayloadTooLargeError):
        status = 413
    else:
        status = 400
    return {"status_code": status, "body": {"status": "error", "message": str(error)}}


class WebhookSourceIntake:
    def __init__(
        self,
        *,
        lookup_session: AsyncSession,
        session_scope: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        secret_reader_for: Callable[[AsyncSession, UserContext], SecretReader],
        waker: StreamWaker,
        event_broker: EventBroker | None,
        settings: Settings,
    ):
        self._lookup_session = lookup_session
        self._session_scope = session_scope
        self._secret_reader_for = secret_reader_for
        self._waker = waker
        self._event_broker = event_broker
        self._settings = settings

    async def handle_webhook_request(
        self,
        webhook_id: str,
        method: str,
        headers: dict[str, str],
        body: Any,
        query_params: dict[str, str],
        raw_body: bytes | None = None,
    ) -> dict[str, Any]:
        source = await find_webhook_source(self._lookup_session, webhook_id)
        if source is None:
            return {
                "status_code": 400,
                "body": {"status": "error", "message": f"Webhook {webhook_id} not found"},
            }
        spec = spec_from_source(source)
        context = UserContext(user_id=spec.created_by, workspace_id=spec.workspace_id)
        with workspace_scope(context.workspace_id):
            async with self._session_scope() as session:
                callback = JournalAppendCallback(
                    journal=StreamJournal(session, context, self._settings.streams),
                    spec=spec,
                    source_id=source.id,
                )
                manager = DefaultWebhookManager(
                    execution_callback=callback,
                    event_broker=self._event_broker,
                    base_url=self._settings.triggers.WEBHOOK_URL,
                    secret_reader=self._secret_reader_for(session, context),
                )
                await manager.register_webhook(spec)
                result = await manager.handle_webhook_request(
                    webhook_id, method, headers, body, query_params, raw_body=raw_body
                )
        if callback.refusal is not None:
            logger.warning(
                "Webhook %s refused by stream %s: %s", webhook_id, spec.stream_id, callback.refusal
            )
            return _refused(callback.refusal)
        receipt = callback.receipt
        if receipt is None:
            return result
        if receipt.appended:
            await self._waker.wake(spec.stream_id)
        return {
            "status_code": 202,
            "body": {
                "status": "accepted" if receipt.appended else "duplicate",
                "sequence": receipt.sequence,
            },
        }

    async def is_healthy(self) -> bool:
        return True
