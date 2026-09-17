"""Turn an inbound email into a normalized channel event.

Two paths produce inbound mail — a provider POSTing a parsed message to our
webhook, and polling a connected IMAP mailbox — and both land here, so a reply
threads identically no matter how the message arrived.

Which JSON keys a provider uses is configuration (``field_map``), not a branch
in this module: every inbound-parse vendor names these fields differently and
none of their names belong in platform code.
"""

from __future__ import annotations

import re
from typing import Any

#: Canonical field names, and the payload keys they read when nothing is mapped.
EMAIL_FIELD_DEFAULTS: dict[str, str] = {
    "from": "from",
    "to": "to",
    "subject": "subject",
    "text": "text",
    "html": "html",
    "message_id": "message_id",
    "in_reply_to": "in_reply_to",
    "references": "references",
}

_MESSAGE_ID_RE = re.compile(r"<[^<>@\s]+@[^<>\s]+>")


def _resolve(node: Any, parts: list[str]) -> Any:
    if not parts:
        return node
    part, rest = parts[0], parts[1:]
    if part.endswith("[]"):
        items = node.get(part[:-2]) if isinstance(node, dict) else None
        if not isinstance(items, list):
            return None
        resolved = [_resolve(item, rest) for item in items]
        return [value for value in resolved if value is not None]
    if isinstance(node, dict):
        return _resolve(node.get(part), rest)
    return None


def _lookup(body: dict[str, Any], field_map: dict[str, str], field: str) -> Any:
    path = field_map.get(field, EMAIL_FIELD_DEFAULTS[field])
    return _resolve(body, path.split("."))


def _as_text(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    # A dict here means the payload nests this field and no field_map said where
    # to look. Stringifying it would feed "{'Name': ...}" to the agent as if it
    # were the sender, so treat it as absent and let the caller notice.
    if value is None or isinstance(value, dict):
        return None
    text = str(value).strip()
    return text or None


def canonical_message_id(value: Any) -> str | None:
    """A message id in its RFC form, with the angle brackets.

    Providers disagree: a raw header keeps ``<...>`` while several JSON APIs
    strip them. Both spellings name the same message, and the thread key is
    compared across sources, so they have to normalize to one.
    """
    text = _as_text(value)
    if not text:
        return None
    return text if text.startswith("<") else f"<{text}>"


def parse_message_ids(value: Any) -> list[str]:
    """Split a References/In-Reply-To header into individual message ids."""
    if isinstance(value, list):
        ids = [canonical_message_id(v) for v in value]
        return [item for item in ids if item]
    text = _as_text(value)
    if not text:
        return []
    found = _MESSAGE_ID_RE.findall(text) or text.split()
    return [item for item in (canonical_message_id(v) for v in found) if item]


def normalize_email(body: Any, field_map: dict[str, str] | None) -> dict[str, Any]:
    """Read one inbound message into the canonical shape.

    A field the payload does not carry stays ``None`` — an email without a
    subject is a real thing, and inventing one would put made-up text in front
    of the agent.
    """
    if not isinstance(body, dict):
        raise ValueError("inbound email payload must be a JSON object")

    field_map = field_map or {}
    recipients = _lookup(body, field_map, "to")
    to_all = (
        [item for item in (_as_text(v) for v in recipients) if item]
        if isinstance(recipients, list)
        else [t for t in [_as_text(recipients)] if t]
    )

    return {
        "from": _as_text(_lookup(body, field_map, "from")),
        "to": to_all[0] if to_all else None,
        "to_all": to_all,
        "subject": _as_text(_lookup(body, field_map, "subject")),
        "text": _as_text(_lookup(body, field_map, "text")),
        "html": _as_text(_lookup(body, field_map, "html")),
        "message_id": canonical_message_id(_lookup(body, field_map, "message_id")),
        "in_reply_to": canonical_message_id(_lookup(body, field_map, "in_reply_to")),
        "references": parse_message_ids(_lookup(body, field_map, "references")),
    }


def thread_key(
    *, message_id: str | None, in_reply_to: str | None, references: list[str]
) -> str | None:
    """The stable identity of a mail thread.

    The root of ``References`` is used rather than the immediate parent so that
    a fork in the thread still resolves to the same conversation. Without any
    message id there is nothing stable to thread on, and the caller gets None
    rather than a key that changes on every message.
    """
    if references:
        return references[0]
    return in_reply_to or message_id


def reply_subject(subject: str | None) -> str:
    if not subject:
        return "Re: (no subject)"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def build_email_channel_origin(
    message: dict[str, Any],
    *,
    trigger_id: str,
    credential_type: str = "email",
    presentation: str = "concise",
) -> dict[str, Any] | None:
    """Routing metadata for replying to this message, or None if there is none.

    ``chat_id`` is the thread key: the task repository looks up a live workflow
    by (agent, chat_id), so a reply continues the existing conversation instead
    of opening a second one.

    ``credential_type`` names the secret blob holding the SMTP settings for the
    reply. It differs from the channel type when the mail arrived by polling: a
    connected mailbox keeps one credential covering both IMAP and SMTP.
    """
    reply_to = message.get("from")
    if not reply_to:
        return None

    message_id = message.get("message_id")
    references = list(message.get("references") or [])
    if message_id and message_id not in references:
        references.append(message_id)

    key = thread_key(
        message_id=message_id,
        in_reply_to=message.get("in_reply_to"),
        references=message.get("references") or [],
    )

    return {
        "type": "email",
        "credential_type": credential_type,
        "trigger_id": trigger_id,
        "chat_id": key,
        "reply_to": reply_to,
        "subject": reply_subject(message.get("subject")),
        "message_id": message_id,
        "references": references,
        "user_display_name": reply_to,
        "presentation": presentation,
    }
