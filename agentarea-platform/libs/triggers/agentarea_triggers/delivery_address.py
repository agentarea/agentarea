"""Where a task an event started replies, and the session it belongs to (ADR-0040 §4).

A chat message is an event like any other. What makes its task answer in the
chat is the task's delivery address — which reply sender, which target, whose
credentials — built here from the event and its catalog entry's ``reply``
block; what makes the next message join the task is its ``session``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.config.duration import parse_duration
from agentarea_common.reserved_task_parameters import (
    DELIVERY_ADDRESS_PARAMETER,
    SESSION_PARAMETER,
)
from agentarea_streams.domain.templates import TemplateContext, render_value

from .domain.models import TriggerSession

if TYPE_CHECKING:
    from agentarea_streams.domain import StreamEvent
    from agentarea_streams.domain.source_types import SourceTypeEntry
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_IDLE_TIMEOUT = "30m"

BodyReader = Callable[[str, str], Awaitable[bytes]]


async def _read_workspace_file(workspace_id: str, path: str) -> bytes:
    from agentarea_common.artifacts import ArtifactService

    data, _ = await ArtifactService().get(workspace_id, path)
    return data


async def event_body(
    data: Mapping[str, Any], workspace_id: str, read: BodyReader = _read_workspace_file
) -> Any:
    """The body as sent: inline, or read back from the workspace file a large one moved to."""
    ref = data.get("body_ref")
    if data.get("body") is None and isinstance(ref, str) and ref:
        return json.loads(await read(workspace_id, ref))
    return data.get("body")


def build_delivery_address(
    entry: SourceTypeEntry,
    *,
    source_id: UUID,
    credential_key: UUID | None,
    trigger_id: UUID,
    session_key: str | None,
    body: Any,
    headers: Mapping[str, str],
) -> dict[str, Any] | None:
    """The address a task replies to, or None when the entry has no reply or the event no target.

    A target field the event does not have is left out (a message outside a
    thread has no thread to answer in); an event with none of them has nowhere
    to answer.
    """
    reply = entry.reply
    if reply is None:
        return None
    target = render_value(reply.target, TemplateContext(body=body, headers=headers))
    if reply.target and not target:
        logger.warning(
            "An event of source %s (%s) has nothing to reply to; its task does not reply",
            source_id,
            entry.slug,
        )
        return None
    return {
        "type": entry.slug,
        "sender": reply.sender,
        "source_id": str(source_id),
        "credential_type": entry.slug,
        "credential_key": str(credential_key) if credential_key is not None else None,
        "trigger_id": str(trigger_id),
        "session_key": session_key,
        "target": target,
        "presentation": reply.presentation,
    }


def task_session(
    setting: TriggerSession | None, entry: SourceTypeEntry | None, session_key: str | None
) -> dict[str, Any] | None:
    """The session a task joins: its key, whether it waits for the next event, for how long.

    None for an event with no session key. The trigger's ``continue`` wins; without
    one, an entry that names sessions continues them.
    """
    if session_key is None:
        return None
    continues = setting.continue_ if setting is not None else None
    if continues is None:
        continues = entry.continues_sessions() if entry is not None else False
    idle_timeout = parse_duration(
        (setting.idle_timeout if setting is not None else None) or DEFAULT_IDLE_TIMEOUT
    )
    return {
        "key": session_key,
        "continue": bool(continues),
        "idle_timeout_seconds": int(idle_timeout.total_seconds()),
    }


@dataclass(frozen=True)
class FiringDelivery:
    """What a stream firing stamps on its task beside the trigger's own parameters."""

    source_type: str | None = None
    stream_event_id: str | None = None
    address: dict[str, Any] | None = None
    session: dict[str, Any] | None = None

    def stamp(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if self.source_type is not None:
            parameters["source_type"] = self.source_type
        if self.stream_event_id is not None:
            parameters["stream_event_id"] = self.stream_event_id
        if self.address is not None:
            parameters[DELIVERY_ADDRESS_PARAMETER] = self.address
        if self.session is not None:
            parameters[SESSION_PARAMETER] = self.session
        return parameters


async def firing_delivery(
    session: AsyncSession,
    event: StreamEvent,
    *,
    trigger_id: UUID,
    session_setting: TriggerSession | None,
    body: Any,
) -> FiringDelivery:
    """The delivery address and session of a task this stream event starts.

    Read from the source that brought the event and its catalog entry. An event
    with no source has neither, and so has a copy (a forward's, a processor's
    output): it keeps its original's source for sender admission, but only the
    original's task answers the sender. ``body`` is the event's body as sent
    (``event_body``), also when a large one was moved to files.
    """
    from agentarea_streams.infrastructure.catalog_source_types import (
        CatalogSourceTypeRepository,
    )
    from agentarea_streams.infrastructure.orm import StreamSourceORM

    base = FiringDelivery(stream_event_id=str(event.id))
    if event.source_id is None or event.depth > 0:
        return base
    source = await session.get(StreamSourceORM, event.source_id)
    if source is None or source.workspace_id != event.workspace_id:
        logger.warning(
            "Event %s names source %s, which is not in its workspace; its task does not reply",
            event.id,
            event.source_id,
        )
        return base
    slug = source.webhook_type
    entry = await CatalogSourceTypeRepository(session).get(slug) if slug else None
    if entry is None:
        logger.error(
            "Source %s is of type %r, which the catalog has no entry for; its task does not reply",
            source.id,
            slug,
        )
        return FiringDelivery(source_type=slug, stream_event_id=str(event.id))
    data = event.data if isinstance(event.data, Mapping) else {}
    headers = data.get("headers")
    return FiringDelivery(
        source_type=slug,
        stream_event_id=str(event.id),
        address=build_delivery_address(
            entry,
            source_id=source.id,
            credential_key=source.credential_key,
            trigger_id=trigger_id,
            session_key=event.session_key,
            body=body,
            headers=headers if isinstance(headers, Mapping) else {},
        ),
        session=task_session(session_setting, entry, event.session_key),
    )
