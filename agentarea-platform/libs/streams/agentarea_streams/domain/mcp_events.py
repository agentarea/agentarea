"""A stream served as MCP Events (SEP-3415): the wire values that do not depend on transport.

Implemented against the SEP-3415 draft at pja-ant/modelcontextprotocol@2ec39b9c
(2026-10-16), an extension of MCP 2026-07-28. Poll and webhook delivery; no
push (``events/stream``), since the platform's MCP mounts are stateless.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .filters import ExternalFilter
from .models import ENVELOPE_VERSION, StreamEvent

EXTENSION_ID = "io.modelcontextprotocol/events"
#: The pre-SEP sketch's top-level capability, which a deployed client still reads.
SKETCH_CAPABILITY = "events"
DRAFT = "SEP-3415 @ 2ec39b9c (2026-10-16), MCP 2026-07-28"

DELIVERY_MODES = ("poll", "webhook")
SUBSCRIPTION_HEADER = "X-MCP-Subscription-Id"

DEFAULT_TTL = timedelta(hours=1)
MIN_TTL = timedelta(minutes=1)
MAX_TTL = timedelta(hours=24)
#: Attempts after the first; past the last the subscription is marked failed.
RETRY_DELAYS = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=2),
)
DEFAULT_MAX_EVENTS = 50
MAX_EVENTS = 500
NEXT_POLL_MS = 10_000
MAX_SUBSCRIPTIONS_PER_WORKSPACE = 100

_SECRET_PREFIX = "whsec_"  # noqa: S105 - the Standard Webhooks prefix, not a secret  # pragma: allowlist secret
_CURSOR_VERSION = "v1"


class ErrorCode(IntEnum):
    INVALID_PARAMS = -32602
    NOT_FOUND = -32023
    FORBIDDEN = -32024
    RESOURCE_EXHAUSTED = -32025
    UNSUPPORTED = -32026
    CALLBACK_ENDPOINT_ERROR = -32027


class EventsError(Exception):
    """A JSON-RPC error of the extension, by its code."""

    def __init__(self, code: ErrorCode, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class EventArguments(BaseModel):
    """What a subscriber narrows a stream to; every field optional."""

    model_config = ConfigDict(extra="forbid")

    kind: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Only events of this kind, or of a kind under it (order matches order.paid).",
    )
    source_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Only events a source of this catalog entry brought (github, telegram).",
    )
    session_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="Only events of this session: one chat, one thread.",
    )

    def to_filter(self) -> ExternalFilter:
        return ExternalFilter(
            kinds=[self.kind] if self.kind else [],
            source_type=self.source_type,
            session_key=self.session_key,
        )

    def canonical(self) -> str:
        return json.dumps(self.model_dump(exclude_none=True), sort_keys=True, separators=(",", ":"))


class EnvelopeAttachment(BaseModel):
    name: str
    mime: str | None = None
    size: int | None = None
    sha256: str | None = None
    ref: str


class EventEnvelope(BaseModel):
    """An event as every subscriber receives it (ADR-0040 §2)."""

    v: int = Field(description="Envelope version.")
    id: str = Field(description="The event id; a repeat of the event has the same one.")
    workspace_id: str
    stream_id: str
    source_id: str | None = None
    source_type: str | None = Field(default=None, description="The source's catalog entry.")
    kind: str
    key: str = Field(description="The key the event was deduplicated by.")
    session_key: str | None = None
    sender: str | None = None
    received_at: datetime
    occurred_at: datetime = Field(description="The provider's own time, else when received.")
    depth: int = Field(description="Causation depth; a forward adds one.")
    correlation_id: str | None = None
    causation_id: str | None = None
    data: dict[str, Any] = Field(
        description="headers (credentials removed) and body as sent; a body over 64 KiB is body_ref."
    )
    attachments: list[EnvelopeAttachment] = Field(default_factory=list)

    @classmethod
    def of(cls, event: StreamEvent) -> EventEnvelope:
        return cls(
            v=ENVELOPE_VERSION,
            id=str(event.id),
            workspace_id=event.workspace_id,
            stream_id=str(event.stream_id),
            source_id=str(event.source_id) if event.source_id else None,
            source_type=event.source_type,
            kind=event.type,
            key=event.event_key,
            session_key=event.session_key,
            sender=event.sender,
            received_at=event.received_at,
            occurred_at=event.time,
            depth=event.depth,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            data=event.data,
            attachments=[
                EnvelopeAttachment(
                    name=a.name, mime=a.mime, size=a.size, sha256=a.sha256, ref=a.ref
                )
                for a in event.attachments
            ],
        )


def input_schema() -> dict[str, Any]:
    return EventArguments.model_json_schema()


def payload_schema() -> dict[str, Any]:
    return EventEnvelope.model_json_schema()


def event_name(workspace_slug: str, stream_id: UUID) -> str:
    """A stream's event type name, the same on every mount: ``<workspace>/<stream id>``."""
    return f"{workspace_slug}/{stream_id}"


def parse_event_name(name: str) -> tuple[str, UUID]:
    """The workspace reference and stream id an event type name holds."""
    workspace, _, stream = name.partition("/")
    try:
        stream_id = UUID(stream)
    except ValueError:
        stream_id = None
    if not workspace or stream_id is None:
        raise EventsError(ErrorCode.NOT_FOUND, f"no event type {name!r}", {"kind": "event"})
    return workspace, stream_id


def occurrence(event: StreamEvent, name: str) -> dict[str, Any]:
    """The ``EventOccurrence`` of an event under the event type ``name``."""
    return {
        "eventId": str(event.id),
        "name": name,
        "timestamp": event.time.isoformat(),
        "data": EventEnvelope.of(event).model_dump(mode="json"),
    }


@dataclass(frozen=True)
class PollCursor:
    """A poll position: the last event seen in the read model, and when the poll was answered."""

    at: datetime
    sequence: int

    def encode(self) -> str:
        raw = f"{_CURSOR_VERSION}:{int(self.at.timestamp() * 1000)}:{self.sequence}"
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, text: str) -> PollCursor:
        try:
            raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode()
            version, millis, sequence = raw.split(":")
            if version != _CURSOR_VERSION:
                raise ValueError(version)
            return cls(
                at=datetime.fromtimestamp(int(millis) / 1000, tz=UTC), sequence=int(sequence)
            )
        except ValueError, UnicodeDecodeError, binascii.Error:
            raise EventsError(
                ErrorCode.INVALID_PARAMS, "cursor is not one this server issued"
            ) from None

    def before(self, window_start: datetime) -> bool:
        """Whether events after this position may have left the read model."""
        return self.at < window_start


def validate_secret(secret: str) -> None:
    """A Standard Webhooks secret: ``whsec_`` and the base64 of 24 to 64 bytes."""
    if not secret.startswith(_SECRET_PREFIX):
        raise EventsError(ErrorCode.INVALID_PARAMS, "delivery.secret must start with whsec_")
    try:
        key = base64.b64decode(secret.removeprefix(_SECRET_PREFIX), validate=True)
    except binascii.Error:
        raise EventsError(ErrorCode.INVALID_PARAMS, "delivery.secret is not base64") from None
    if not 24 <= len(key) <= 64:
        raise EventsError(
            ErrorCode.INVALID_PARAMS, "delivery.secret must encode 24 to 64 random bytes"
        )


def subscription_id(subscriber: str, url: str, stream_id: UUID, arguments: EventArguments) -> str:
    """The routing handle of the subscription key (principal, url, event, arguments)."""
    key = json.dumps(
        [subscriber, url, str(stream_id), arguments.canonical()], separators=(",", ":")
    )
    return "sub_" + hashlib.sha256(key.encode()).hexdigest()[:32]


def grant_refresh_before(ttl_ms: int | None, *, now: datetime) -> datetime:
    """The expiry granted for a suggested TTL; no expiry (``None``) is answered with the longest."""
    if ttl_ms is None:
        return now + MAX_TTL
    return now + min(max(timedelta(milliseconds=ttl_ms), MIN_TTL), MAX_TTL)


def sign(secret: str, message_id: str, timestamp: int, body: bytes) -> str:
    """``webhook-signature``: ``v1,`` and the base64 HMAC-SHA256 over ``id.timestamp.body``."""
    key = base64.b64decode(secret.removeprefix(_SECRET_PREFIX))
    digest = hmac.new(key, f"{message_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return f"v1,{base64.b64encode(digest).decode()}"


def delivery_headers(
    *, secret: str, message_id: str, timestamp: int, body: bytes, subscription: str
) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "webhook-id": message_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": sign(secret, message_id, timestamp, body),
        SUBSCRIPTION_HEADER: subscription,
    }


def control_message_id(kind: str) -> str:
    return f"msg_{kind}_{secrets.token_hex(12)}"


def encode_body(body: dict[str, Any]) -> bytes:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
