"""What the platform reads off an inbound event, by its catalog entry's templates (ADR-0040 §2).

Only the envelope: kind, key, session, sender, time, where the files are, and
the headers without credentials. The body is the agent's to read.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

from .source_types import EventOverrides, SourceTypeEntry, Template, Verification
from .templates import TemplateContext, path_value, render_first

#: The kind of an event whose entry names none that renders.
FALLBACK_KIND = "event"

_CREDENTIAL_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "proxy-authorization"})
_CREDENTIAL_HEADER = re.compile(r"^x-.*-(token|secret)$|signature|api-?key", re.IGNORECASE)


@dataclass(frozen=True)
class EventFields:
    kind: str
    #: None: the event carries nothing that names it, so it is never a repeat.
    key: str | None
    #: ``<source_id>:<value>``, or None when the provider has no sessions.
    session_key: str | None
    sender: str | None
    occurred_at: datetime | None


def without_credentials(
    headers: Mapping[str, str], verification: Verification | None
) -> dict[str, str]:
    """The headers an event keeps: none that carries a credential or a signature over one."""
    signed = {verification.header.lower()} if verification and verification.header else set()
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in _CREDENTIAL_HEADERS
        and name.lower() not in signed
        and not _CREDENTIAL_HEADER.search(name)
    }


def _template(override: Template | None, own: Template | None) -> Template | None:
    return override if override is not None else own


def read_event(
    entry: SourceTypeEntry,
    overrides: EventOverrides | None,
    *,
    source_id: UUID,
    headers: Mapping[str, str],
    body: Any,
) -> EventFields:
    """Kind, key, session, sender and time of one event, by the entry's templates.

    A source's own templates (a generic webhook's) stand in for the entry's
    kind, key and session key.
    """
    context = TemplateContext(body=body, headers=headers)
    templates = entry.event
    own = overrides or EventOverrides()
    session = render_first(_template(own.session_key, templates.session_key), context)
    return EventFields(
        kind=render_first(_template(own.kind, templates.kind), context) or FALLBACK_KIND,
        key=render_first(_template(own.key, templates.key), context),
        session_key=f"{source_id}:{session}" if session is not None else None,
        sender=render_first(templates.sender, context),
        occurred_at=provider_time(render_first(templates.occurred_at, context)),
    )


def provider_time(value: str | None) -> datetime | None:
    """A provider's own time: unix seconds (or milliseconds), ISO 8601 or RFC 2822; None if none."""
    if value is None:
        return None
    text = value.strip()
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        seconds = number / 1000 if number > 1e11 else number
        return datetime.fromtimestamp(seconds, tz=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


#: A path ending in this names an object of files keyed by id (Discord's resolved attachments).
_EACH_VALUE = ".*"
#: A path ending in this names the last entry of a list: Telegram's photo is one picture in
#: several sizes, smallest first.
_LAST_ITEM = "[-1]"


def _list_path(path: str) -> str:
    return path.removesuffix(_EACH_VALUE).removesuffix(_LAST_ITEM)


def attachment_path(entry: SourceTypeEntry, body: Any) -> str | None:
    """The first of the entry's attachment paths present in the body."""
    attachments = entry.event.attachments
    if attachments is None:
        return None
    for path in attachments.path.split("|"):
        path = path.strip()
        if path and path_value(body, _list_path(path)) not in (None, [], {}):
            return path
    return None


def attachment_items(body: Any, path: str) -> list[Mapping[str, Any]]:
    """The file objects at ``path``.

    A list of them, or one, each value of ``path.*``, or the last entry of ``path[-1]``.
    """
    if path.endswith(_EACH_VALUE):
        value = path_value(body, path.removesuffix(_EACH_VALUE))
        values = list(value.values()) if isinstance(value, Mapping) else []
        return [item for item in values if isinstance(item, Mapping)]
    if path.endswith(_LAST_ITEM):
        value = path_value(body, path.removesuffix(_LAST_ITEM))
        last = value[-1] if isinstance(value, list) and value else None
        return [last] if isinstance(last, Mapping) else []
    value = path_value(body, path)
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []
