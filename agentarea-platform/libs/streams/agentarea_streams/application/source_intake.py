"""One way in for a source's event (ADR-0040 §3): envelope, files to storage, the bus.

Webhook intake calls this after verification and the handshake; the poll
consumer calls it for each item the Go event-service fetched. The entry's
templates name the event; a body larger than ``MAX_INLINE_BODY_BYTES`` and the
bytes of inline attachments move to the workspace's files, so neither the
broker nor the read model carries file bytes.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.envelope import (
    EventFields,
    attachment_items,
    attachment_path,
    carried_depth,
    chain_id,
    read_event,
    without_credentials,
)
from ..domain.keys import MAX_INLINE_BODY_BYTES, encoded_size, event_id_for
from ..domain.models import AppendResult, Attachment
from ..domain.source_types import EventOverrides, SourceTypeEntry
from ..domain.verification import configured
from ..infrastructure.bus import StreamBus
from ..infrastructure.orm import StreamSourceORM
from .ingest import StreamIngest

logger = logging.getLogger(__name__)

#: Where an event's offloaded body and files live in its workspace's files.
EVENT_FILES_PREFIX = "events"
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class EventFiles(Protocol):
    """Workspace file storage, as ``ArtifactService`` offers it."""

    async def put(
        self, workspace_id: str, path: str, data: bytes, content_type: str | None = None
    ) -> Any: ...


class _ArtifactFiles:
    """``ArtifactService`` made on first use: most events move no file."""

    def __init__(self) -> None:
        self._service: Any = None

    async def put(
        self, workspace_id: str, path: str, data: bytes, content_type: str | None = None
    ) -> Any:
        if self._service is None:
            from agentarea_common.artifacts import ArtifactService

            self._service = ArtifactService()
        return await self._service.put(workspace_id, path, data, content_type)


def event_file_path(stream_id: UUID, event_id: UUID, name: str) -> str:
    return f"{EVENT_FILES_PREFIX}/{stream_id}/{event_id}/{name}"


def _safe_name(name: str) -> str:
    cleaned = _UNSAFE_NAME.sub("_", name).strip("._")
    return cleaned[:120] or "file"


def _str(item: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _int(item: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


class SourceIntake:
    def __init__(self, *, bus: StreamBus, files: EventFiles, settings: EventStreamSettings):
        self._bus = bus
        self._files = files
        self._settings = settings

    async def ingest(
        self,
        session: AsyncSession,
        source: StreamSourceORM,
        entry: SourceTypeEntry,
        *,
        body: Any,
        headers: Mapping[str, str],
        received_at: datetime,
        kind_override: str | None = None,
        key_override: str | None = None,
    ) -> AppendResult:
        """Publish one event of ``source``; a repeat of its key is the same event.

        Raises the ``StreamError`` family as ``StreamIngest.append`` does.
        """
        overrides = (
            EventOverrides.model_validate(source.event_templates)
            if source.event_templates
            else None
        )
        fields = read_event(entry, overrides, source_id=source.id, headers=headers, body=body)
        # No key: nothing names the event, so every delivery is a new one.
        key = key_override or fields.key or f"recv:{uuid4()}"
        event_id = event_id_for(source.stream_id, key)
        workspace_id = source.workspace_id

        body, attachments = await self._store_attachments(
            entry, workspace_id, source.stream_id, event_id, body
        )
        body_ref: str | None = None
        if body is not None and encoded_size({"body": body}) > MAX_INLINE_BODY_BYTES:
            body_ref = event_file_path(source.stream_id, event_id, "body.json")
            await self._files.put(
                workspace_id,
                body_ref,
                json.dumps(body, ensure_ascii=False, default=str).encode(),
                "application/json",
            )
            body = None

        # The header this source verifies by, which its config may rename, carries a credential.
        scheme = (
            configured(entry.verification, source.webhook_config or {})
            if entry.verification
            else None
        )
        depth, correlation_id, causation_id = self._carried_chain(source.id, fields)
        event = IntegrationEvent(
            type=kind_override or fields.kind,
            source=f"/sources/{source.id}",
            subject=fields.session_key,
            time=fields.occurred_at or received_at,
            correlation_id=correlation_id,
            causation_id=causation_id,
            data={
                "headers": without_credentials(headers, scheme),
                "body": body,
                "body_ref": body_ref,
            },
        )
        context = UserContext(user_id=source.created_by, workspace_id=workspace_id)
        with workspace_scope(workspace_id):
            ingest = StreamIngest(
                session, context, self._settings, self._bus, clock=lambda: received_at
            )
            return await ingest.append(
                source.stream_id,
                event,
                event_key=key,
                source_id=source.id,
                depth=depth,
                event_id=event_id,
                source_type=entry.slug,
                session_key=fields.session_key,
                sender=fields.sender,
                attachments=attachments,
            )

    def _carried_chain(
        self, source_id: UUID, fields: EventFields
    ) -> tuple[int, str | None, str | None]:
        """Depth, correlation and causation the producer named, the ones that pass the checks."""
        depth = 0
        if fields.depth is not None:
            carried = carried_depth(fields.depth, self._settings.FORWARD_DEPTH)
            if carried is None:
                logger.warning(
                    "Source %s names depth %r, not a count; the event starts a chain",
                    source_id,
                    fields.depth,
                )
            else:
                depth = carried
        ids: list[str | None] = []
        for name, value in (
            ("correlation_id", fields.correlation_id),
            ("causation_id", fields.causation_id),
        ):
            checked = chain_id(value) if value is not None else None
            if value is not None and checked is None:
                logger.warning("Source %s names %s %r, not a UUID; ignored", source_id, name, value)
            ids.append(checked)
        return depth, ids[0], ids[1]

    async def _store_attachments(
        self,
        entry: SourceTypeEntry,
        workspace_id: str,
        stream_id: UUID,
        event_id: UUID,
        body: Any,
    ) -> tuple[Any, list[Attachment]]:
        """The body without inline file bytes, and the event's attachments."""
        path = attachment_path(entry, body)
        if path is None or entry.event.attachments is None:
            return body, []
        fetch = entry.event.attachments.fetch
        if fetch != "inline":
            return body, [
                Attachment(
                    name=_str(item, "file_name", "name", "filename", "title") or "file",
                    mime=_str(item, "mime_type", "mimetype", "mime", "content_type"),
                    size=_int(item, "file_size", "size"),
                    ref=json.dumps({"fetch": fetch, "item": item}, separators=(",", ":")),
                    stored=False,
                )
                for item in attachment_items(body, path)
            ]
        body = copy.deepcopy(body)
        attachments: list[Attachment] = []
        for index, item in enumerate(attachment_items(body, path)):
            if not isinstance(item, dict):
                continue
            encoded = item.pop("content_base64", None)
            if not isinstance(encoded, str):
                continue
            try:
                data = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                logger.warning("Attachment %d of event %s is not base64; left out", index, event_id)
                continue
            name = _str(item, "name", "filename", "file_name") or f"attachment-{index}"
            mime = _str(item, "mime", "mime_type", "content_type")
            ref = event_file_path(stream_id, event_id, f"{index}-{_safe_name(name)}")
            await self._files.put(workspace_id, ref, data, mime)
            item["ref"] = ref
            attachments.append(
                Attachment(
                    name=name,
                    mime=mime,
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    ref=ref,
                    stored=True,
                )
            )
        return body, attachments


async def ingest_source_event(
    session: AsyncSession,
    source: StreamSourceORM,
    entry: SourceTypeEntry,
    *,
    body: Any,
    headers: Mapping[str, str],
    received_at: datetime,
    kind_override: str | None = None,
    key_override: str | None = None,
) -> AppendResult:
    """``SourceIntake.ingest`` with the process's bus and workspace file storage."""
    from agentarea_common.config import get_settings
    from agentarea_common.di.container import resolve

    intake = SourceIntake(
        bus=resolve(StreamBus), files=_ArtifactFiles(), settings=get_settings().streams
    )
    return await intake.ingest(
        session,
        source,
        entry,
        body=body,
        headers=headers,
        received_at=received_at,
        kind_override=kind_override,
        key_override=key_override,
    )
