"""A source type: one catalog entry saying how a provider's events arrive and are read (ADR-0040 §2).

Entries live in the catalog (``registry_items`` of type ``source_types``,
shipped in ``data/catalog/source-types.json``); nothing in code names a
provider. Events reads the inbound part of an entry; Delivery reads ``reply``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The slug of the entry for a provider the catalog has no entry for.
GENERIC_WEBHOOK = "generic_webhook"


class SourceField(BaseModel):
    """A credential or setting a member fills in for a source of this type."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    placeholder: str = ""
    required: bool = True
    #: The platform generates the value when the member leaves it empty.
    issued: bool = False
    #: The form of a value: ``whsec`` is a Standard Webhooks secret, ``whsec_<base64>``.
    format: Literal["token", "whsec"] = "token"


class Verification(BaseModel):
    """How a webhook request proves it came from the provider: one of five schemes."""

    model_config = ConfigDict(extra="forbid")

    scheme: Literal["hmac", "hmac_timestamped", "ed25519", "shared_token", "api_lookup", "none"]
    #: The credential key holding the secret, the public key or the API key.
    secret: str | None = None
    header: str | None = None
    algorithm: Literal["sha1", "sha256", "sha384", "sha512"] = "sha256"
    encoding: Literal["hex", "base64"] = "hex"
    prefix: str = ""
    #: hmac_timestamped / ed25519: where the timestamp and the delivery id are.
    timestamp_header: str | None = None
    id_header: str | None = None
    #: hmac_timestamped: the signed text, from {timestamp}, {id} and {body}.
    payload: str = "{body}"
    #: hmac_timestamped: how the signature header carries its parts.
    #: kv: ``t=<ts>,v1=<sig>``; list: ``v1,<sig> v1,<sig>``; plain: ``<prefix><sig>``.
    signature_format: Literal["plain", "kv", "list"] = "plain"
    timestamp_key: str = "t"
    signature_key: str = "v1"
    #: A secret written ``whsec_<base64>`` is decoded before use.
    secret_format: Literal["raw", "whsec"] = "raw"  # noqa: S105 - a format name, not a secret
    tolerance_seconds: int = 300
    #: api_lookup: read the notified object back and compare it.
    request: dict[str, Any] | None = None
    collection_from: str | None = None
    collections: dict[str, str] = Field(default_factory=dict)
    expect: dict[str, str] = Field(default_factory=dict)
    #: api_lookup: a state the object may already have moved on to from the notified one.
    later: dict[str, list[str]] = Field(default_factory=dict)
    #: api_lookup: body paths recorded from the lookup in place of what the notification
    #: said, from {fetched} (the object the API holds) and {notified.object}/{notified.state}.
    record: dict[str, str] = Field(default_factory=dict)
    #: Settings a member may override per source, by config key.
    configurable: list[str] = Field(default_factory=list)
    #: Headers every request must carry besides the signature (MCP Events' subscription id).
    required_headers: list[str] = Field(default_factory=list)


class Handshake(BaseModel):
    """A request the provider sends to check the endpoint, answered without recording it."""

    model_config = ConfigDict(extra="forbid")

    when: str
    equals: str
    respond: dict[str, Any]


class Request(BaseModel):
    """An HTTP request described by templates."""

    model_config = ConfigDict(extra="forbid")

    method: str = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")


class Registration(BaseModel):
    """How the Go reconciler points the provider at the source's webhook URL, and takes it back.

    Either two templated requests, or a ``transport`` that is a protocol of its
    own: ``mcp_events`` subscribes with events/subscribe and refreshes the
    subscription before it expires.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    register_request: Request | None = Field(default=None, alias="register")
    unregister: Request | None = None
    transport: Literal["mcp_events"] | None = None

    @model_validator(mode="after")
    def _one_way(self) -> Registration:
        if (self.register_request is None) == (self.transport is None):
            raise ValueError("a registration has either a register request or a transport")
        if self.transport is not None and self.unregister is not None:
            raise ValueError("a registration transport unregisters by its own protocol")
        return self


class Signal(BaseModel):
    """A request that reports on the source itself, not an event of it.

    ``gap``: events may be missing; recorded as a ``source.gap`` event keyed by
    ``key``. ``ended``: the provider ended the subscription; the source records
    ``reason`` and the reconciler subscribes again.
    """

    model_config = ConfigDict(extra="forbid")

    when: str
    equals: str
    signal: Literal["gap", "ended"]
    key: str
    reason: str = ""


class Poll(BaseModel):
    """How the Go event-service fetches the events of a poll source."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["http_json", "feed", "imap", "mcp_events"]
    request: Request | None = None
    items: str | None = None
    cursor: str | None = None
    interval: str = "60s"
    #: imap: templates for host, port, use_ssl, mailbox, username, password.
    imap: dict[str, str] | None = None


class Attachments(BaseModel):
    """Where an event's files are and how they are got."""

    model_config = ConfigDict(extra="forbid")

    #: Path to the list of files (inline: objects with name, mime, content_base64).
    path: str
    #: ``inline``: the bytes are in the event and move to storage at intake;
    #: anything else names a provider fetch done when a task opens the file.
    fetch: str = "inline"


#: One template, or several of which the first that renders is the value.
Template = str | list[str]


class EventTemplates(BaseModel):
    """How an event of this type is named and keyed, as template substitutions."""

    model_config = ConfigDict(extra="forbid")

    kind: Template
    key: Template | None = None
    session_key: Template | None = None
    sender: Template | None = None
    occurred_at: Template | None = None
    #: The chain the producer's own event belongs to, when it is a platform like this one
    #: (an MCP Events server sending its stream events). Untrusted: read, checked, and used
    #: only to make the chain longer, never shorter.
    depth: Template | None = None
    correlation_id: Template | None = None
    causation_id: Template | None = None
    attachments: Attachments | None = None


class EventOverrides(BaseModel):
    """What one source may set in place of its entry's templates (a generic webhook's own key)."""

    model_config = ConfigDict(extra="forbid")

    kind: Template | None = None
    key: Template | None = None
    session_key: Template | None = None


class Admission(BaseModel):
    """Who may reach an agent through this source: senders linked to a platform user.

    The sender's account at the provider resolves to a platform user only
    through a link they proved (``identity`` names the provider of the link).
    """

    model_config = ConfigDict(extra="forbid")

    identity: str
    #: The sender's own id at the provider, as the identity link stores it.
    external_id: Template
    #: Where a notice to the sender (how to link, no access) is sent.
    chat: Template
    text: Template | None = None
    #: Renders to ``private_value`` in a one-to-one chat; others are not admitted.
    private: Template | None = None
    private_value: str = "private"
    #: Renders to ``true`` when the sender is a bot, which is never admitted.
    is_bot: Template | None = None


class Reply(BaseModel):
    """How a task started by an event of this type answers where the event came from."""

    model_config = ConfigDict(extra="forbid")

    sender: Literal["http", "telegram_live", "smtp"]
    target: dict[str, str] = Field(default_factory=dict)
    presentation: Literal["concise", "summary", "silent"] = "concise"
    request: Request | None = None
    markup: Literal["slack", "discord", "telegram", "plain"] = "plain"
    limit: int | None = None
    #: An error answer with this text in it is permanent (bad token, gone chat).
    permanent_errors: list[str] = Field(default_factory=list)


class SourceTypeEntry(BaseModel):
    """One provider, as the catalog describes it."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str = ""
    icon: str = "webhook"
    #: ``platform``: written by the platform only; no member adds a source of it.
    delivery: Literal["webhook", "poll", "both", "platform"]
    credentials: list[SourceField] = Field(default_factory=list)
    config: list[SourceField] = Field(default_factory=list)
    verification: Verification | None = None
    handshake: list[Handshake] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    registration: Registration | None = None
    poll: Poll | None = None
    event: EventTemplates
    events: list[str] = Field(default_factory=list)
    admission: Admission | None = None
    reply: Reply | None = None

    def accepts(self, kind: str) -> bool:
        """Whether a source of ``kind`` (``webhook`` / ``poll``) can be of this type."""
        return self.delivery == "both" or self.delivery == kind

    def secret_keys(self) -> set[str]:
        return {field.key for field in self.credentials}

    def continues_sessions(self) -> bool:
        """Whether a trigger on this type joins a session's next event by default."""
        return self.event.session_key is not None
