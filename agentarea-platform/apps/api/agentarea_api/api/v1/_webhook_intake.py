"""Public webhook intake: the source's catalog entry verifies, answers handshakes and names the event.

Find the source by its webhook id, read its entry, verify the request by the
entry's scheme with the source's credentials, answer a handshake without
recording it, and hand everything else to ``SourceIntake``: 202 with the event
id, ``duplicate`` for a repeat of the same key.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

import httpx
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config import Settings
from agentarea_common.outbound import Destination, outbound_client
from agentarea_streams.application.source_credentials import (
    CredentialsUnavailableError,
    SecretReader,
    SecretStoreUnreachableError,
    read_source_credentials,
)
from agentarea_streams.application.source_intake import EventFiles, SourceIntake
from agentarea_streams.domain import StreamError, StreamNotFoundError, StreamQuotaExceededError
from agentarea_streams.domain.source_types import SourceTypeEntry
from agentarea_streams.domain.templates import TemplateContext, render, render_value
from agentarea_streams.domain.verification import (
    VerificationError,
    configured,
    verify_request,
)
from agentarea_streams.infrastructure.bus import StreamBus
from agentarea_streams.infrastructure.catalog_source_types import CatalogSourceTypeRepository
from agentarea_streams.infrastructure.repository import find_webhook_source
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

LOOKUP_TIMEOUT_SECONDS = 10.0


class ProviderUnreachableError(Exception):
    """The provider's API could not be asked; the sender should retry."""


def _answer(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"status_code": status, "body": body}


def _error(status: int, message: str) -> dict[str, Any]:
    return _answer(status, {"status": "error", "message": message})


async def provider_lookup(method: str, url: str, auth: tuple[str, str] | None) -> tuple[int, Any]:
    """Read the notified object back from a provider (``api_lookup``), as the source's member."""
    if ".." in httpx.URL(url).path.split("/"):
        raise VerificationError("the lookup URL climbs out of its path")
    try:
        async with outbound_client(
            Destination.VENDOR, auth=auth, timeout=LOOKUP_TIMEOUT_SECONDS
        ) as client:
            response = await client.request(method, url)
    except httpx.HTTPError as error:
        raise ProviderUnreachableError(url) from error
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


def handshake_answer(entry: SourceTypeEntry, headers: dict[str, str], body: Any) -> Any | None:
    """What to answer a provider's endpoint check, or None when the request is an event."""
    context = TemplateContext(body=body, headers=headers)
    for handshake in entry.handshake:
        if render(handshake.when, context) == handshake.equals:
            return render_value(handshake.respond, context)
    return None


class WebhookSourceIntake:
    def __init__(
        self,
        *,
        session_scope: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        secret_reader_for: Callable[[AsyncSession, UserContext], SecretReader],
        bus: StreamBus,
        files: EventFiles,
        settings: Settings,
        lookup: Callable[..., Any] = provider_lookup,
    ):
        self._session_scope = session_scope
        self._secret_reader_for = secret_reader_for
        self._intake = SourceIntake(bus=bus, files=files, settings=settings.streams)
        self._lookup = lookup

    async def handle_webhook_request(
        self,
        webhook_id: str,
        method: str,
        headers: dict[str, str],
        body: Any,
        raw_body: bytes,
    ) -> dict[str, Any]:
        received_at = datetime.now(UTC)
        # One session per request: lookup, catalog read, secret read and append share it.
        async with self._session_scope() as session:
            source = await find_webhook_source(session, webhook_id)
            if source is None:
                return _error(404, f"Webhook {webhook_id} not found")
            if method.upper() != "POST":
                return _error(405, f"Method {method} not allowed; send POST")
            slug = source.webhook_type or ""
            entry = await CatalogSourceTypeRepository(session).get(slug)
            if entry is None:
                logger.error("Webhook %s: source type %r is not in the catalog", webhook_id, slug)
                return _error(400, f"Source type {slug!r} is not in the catalog")
            if entry.verification is None:
                logger.error("Webhook %s: source type %r verifies no webhook", webhook_id, slug)
                return _error(400, f"Source type {slug!r} does not take webhooks")
            if source.credential_key is None:
                raise RuntimeError(f"webhook source {source.id} is stored without a credential key")
            context = UserContext(user_id=source.created_by, workspace_id=source.workspace_id)
            with workspace_scope(source.workspace_id):
                try:
                    credentials = await read_source_credentials(
                        self._secret_reader_for(session, context), slug, source.credential_key
                    )
                    scheme = configured(entry.verification, source.webhook_config or {})
                    body = await verify_request(
                        scheme,
                        headers=headers,
                        raw_body=raw_body,
                        body=body,
                        credentials=credentials,
                        config=source.webhook_config or {},
                        lookup=self._lookup,
                    )
                except (SecretStoreUnreachableError, ProviderUnreachableError):
                    logger.error("Webhook %s could not be verified now", webhook_id, exc_info=True)
                    return _error(503, "The webhook could not be verified now; retry the delivery")
                except (CredentialsUnavailableError, ValidationError, VerificationError) as error:
                    logger.warning("Webhook %s refused: %s", webhook_id, error)
                    return _error(401, "Verification failed")

                answer = handshake_answer(entry, headers, body)
                if answer is not None:
                    return _answer(200, answer)

                stream_id = source.stream_id
                try:
                    receipt = await self._intake.ingest(
                        session, source, entry, body=body, headers=headers, received_at=received_at
                    )
                except StreamQuotaExceededError as error:
                    await session.rollback()
                    return _error(429, str(error))
                except StreamNotFoundError as error:
                    await session.rollback()
                    return _error(404, str(error))
                except StreamError as error:
                    await session.rollback()
                    return _error(400, str(error))
                except Exception:
                    await session.rollback()
                    logger.error(
                        "Webhook %s could not be recorded in stream %s",
                        webhook_id,
                        stream_id,
                        exc_info=True,
                    )
                    return _error(503, "The webhook could not be recorded; retry the delivery")
        return _answer(
            202,
            {
                "status": "accepted" if receipt.appended else "duplicate",
                "event_id": str(receipt.event_id),
            },
        )

    async def is_healthy(self) -> bool:
        return True
