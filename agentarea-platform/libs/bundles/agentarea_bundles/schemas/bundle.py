"""Canonical agent-package format (v0.1.0).

This is the *internal* normalized representation. External sources (a hand
authored YAML, a Claude plugin, a github URL) are parsed into this single
object by an adapter; analysis and installation only ever operate on it.

Design notes:
- References between entities are by ``key`` (never DB ids), so a package is
  portable. The installer resolves keys to real ids at install time.
- The only place user-supplied values enter is :class:`SetupField`. Everything
  else references them via ``${setup.<key>}`` placeholders.
- ``json_spec`` on an MCP is the native runtime shape consumed by the MCP
  service (``type``: ``command`` | ``docker`` | ``url``) — no second schema.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "0.1.0"

# ${setup.<key>} placeholder, e.g. "Bearer ${setup.github_token}"
_PLACEHOLDER_RE = re.compile(r"\$\{setup\.([a-zA-Z0-9_]+)\}")

_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


def setup_refs(value: Any) -> list[str]:
    """Return the setup-field keys referenced by ``${setup.x}`` in a string."""
    if not isinstance(value, str):
        return []
    return _PLACEHOLDER_RE.findall(value)


def resolve_placeholders(value: str, setup_values: dict[str, Any]) -> str:
    """Substitute ``${setup.<key>}`` occurrences with values from ``setup_values``.

    Missing keys are left as-is; completeness is enforced by the installer so
    the failure is reported as a structured issue rather than a silent blank.
    """

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in setup_values and setup_values[key] is not None:
            return str(setup_values[key])
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_sub, value)


class SetupFieldType(StrEnum):
    """Input widget / storage hint for a setup field."""

    SECRET = "secret"  # noqa: S105 - enum value, not a credential; stored via secret manager
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"


class SetupField(BaseModel):
    """A single value the user must provide before the package can run.

    This is the generalized analogue of a Claude plugin ``userConfig`` entry
    and mirrors the existing MCP ``env_schema`` (KeyValueInput) shape.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, description="Stable identifier referenced via ${setup.key}.")
    label: str = Field(min_length=1, description="Human-readable label rendered in the form.")
    type: SetupFieldType = Field(default=SetupFieldType.STRING)
    required: bool = Field(default=False)
    help: str | None = Field(default=None, description="Help text shown beneath the field.")
    default: Any | None = Field(default=None)
    options: list[str] | None = Field(default=None, description="Choices for type='select'.")
    min: float | None = Field(default=None, description="Lower bound for type='number'.")
    max: float | None = Field(default=None, description="Upper bound for type='number'.")

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError(f"setup key '{v}' must match [a-zA-Z][a-zA-Z0-9_]*")
        return v

    @model_validator(mode="after")
    def _check_select(self) -> SetupField:
        if self.type is SetupFieldType.SELECT and not self.options:
            raise ValueError(f"setup field '{self.key}' is a select but has no options")
        return self


class BundleMcp(BaseModel):
    """An MCP server to provision for the package."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, description="In-package reference key (agents point at this).")
    name: str = Field(min_length=1, description="Instance display name created in the workspace.")
    json_spec: dict[str, Any] = Field(
        description="Native MCP runtime spec. Must include 'type' (command|docker|url)."
    )
    bindings: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Maps an env var / header name the server needs to a ${setup.x} "
            "reference, e.g. {'GITHUB_TOKEN': '${setup.github_token}'}."
        ),
    )

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError(f"mcp key '{v}' must match [a-zA-Z][a-zA-Z0-9_]*")
        return v


class BundleSkill(BaseModel):
    """A skill to create for the package."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    # v0.1.0 supports inline content and github; zip/s3 import comes later.
    source_type: Literal["content", "github"] = "content"
    content: str | None = Field(
        default=None, description="SKILL.md markdown for source_type=content."
    )
    source_url: str | None = Field(default=None, description="Repo URL for source_type=github.")

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError(f"skill key '{v}' must match [a-zA-Z][a-zA-Z0-9_]*")
        return v

    @model_validator(mode="after")
    def _check_source(self) -> BundleSkill:
        if self.source_type == "content" and not self.content:
            raise ValueError(f"skill '{self.key}' is source_type=content but has no content")
        if self.source_type == "github" and not self.source_url:
            raise ValueError(f"skill '{self.key}' is source_type=github but has no source_url")
        return self


class BundleAgent(BaseModel):
    """An agent to create for the package."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    instruction: str = Field(default="", max_length=20000)
    # Literal provider model id (e.g. "gpt-4o") or a ${setup.x} reference.
    model: str | None = Field(default=None)
    mcps: list[str] = Field(default_factory=list, description="BundleMcp keys to attach as tools.")
    skills: list[str] = Field(default_factory=list, description="BundleSkill keys to attach.")

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError(f"agent key '{v}' must match [a-zA-Z][a-zA-Z0-9_]*")
        return v


class BundleAutomation(BaseModel):
    """A scheduled run of one of the package's agents (maps to a CronTrigger).

    Automations are imported disabled by default; the user enables them after
    verifying connections, mirroring the Zapier/Make "connect then activate"
    flow.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    type: Literal["cron"] = "cron"
    cron: str = Field(min_length=1, description="5- or 6-field cron expression.")
    timezone: str = Field(default="UTC")
    agent: str = Field(min_length=1, description="BundleAgent key to invoke.")
    prompt: str = Field(min_length=1, description="Task query passed to the agent on each run.")
    enabled: bool = Field(default=False)

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError(f"automation key '{v}' must match [a-zA-Z][a-zA-Z0-9_]*")
        return v


class BundlePolicy(BaseModel):
    """A governance rule the package installs (maps to a PolicyRule).

    Portable like everything else: ``subject`` is the literal "workspace" or a
    BundleAgent ``key`` (never a DB id); the installer resolves it to a real
    subject id. ``target``/``effect``/``params`` mirror the unified governance
    rule model, so this is "our policy format" — not a new one.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    subject: str = Field(
        default="workspace",
        description='"workspace" or a BundleAgent key the rule binds to.',
    )
    target: str = Field(
        min_length=1,
        description='Selector, e.g. "tool:send_email", "spend", "content", "*".',
    )
    effect: Literal["allow", "deny", "cap", "approval", "safety"]
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Effect-specific params, e.g. {amount_usd, period} for cap.",
    )
    condition: str | None = Field(default=None, description="Optional CEL condition.")
    priority: int = Field(default=0)
    enabled: bool = Field(default=True)
    message: str | None = Field(default=None, description="Human-readable reason.")

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError(f"policy key '{v}' must match [a-zA-Z][a-zA-Z0-9_]*")
        return v


class BundleChannel(BaseModel):
    """A messaging channel that lets an agent receive and reply to messages.

    Installs as an inbound trigger (e.g. a Telegram webhook): a message to the
    bot becomes a task for ``agent``, and the reply is delivered back on the same
    channel. Credentials (a bot token) enter via ``bindings`` → ``${setup.x}``,
    exactly like an MCP's secret bindings, so the token is never inlined.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    type: Literal["telegram"] = Field(
        default="telegram", description="Channel provider. Only Telegram in v0.1.0."
    )
    name: str = Field(min_length=1, description="Display name for the created channel trigger.")
    agent: str = Field(min_length=1, description="BundleAgent key that handles inbound messages.")
    bindings: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Maps a credential the channel needs to a ${setup.x} reference, e.g. "
            "{'bot_token': '${setup.telegram_bot_token}'}."
        ),
    )
    prompt: str = Field(
        default="Handle the incoming message: {{ message_text }}",
        min_length=1,
        description="Task query template used for each inbound message.",
    )
    enabled: bool = Field(default=False)

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError(f"channel key '{v}' must match [a-zA-Z][a-zA-Z0-9_]*")
        return v


class BundleMetadata(BaseModel):
    """Marketplace presentation metadata (parity with plugin/app listings)."""

    model_config = ConfigDict(extra="forbid")

    developer: str | None = Field(default=None, description="Publisher name.")
    category: str | None = Field(default=None)
    capabilities: list[str] = Field(
        default_factory=list, description='e.g. ["interactive", "write"].'
    )
    icon: str | None = Field(default=None, description="Icon URL or asset reference.")
    website: str | None = Field(default=None)
    privacy_url: str | None = Field(default=None)
    terms_url: str | None = Field(default=None)


class Bundle(BaseModel):
    """The canonical, fully-inlined package object."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=SCHEMA_VERSION)
    name: str = Field(min_length=1, description="Stable package identifier (idempotency key).")
    display_name: str | None = Field(default=None)
    description: str = Field(default="")
    metadata: BundleMetadata = Field(default_factory=BundleMetadata)
    setup: list[SetupField] = Field(default_factory=list)
    mcps: list[BundleMcp] = Field(default_factory=list)
    skills: list[BundleSkill] = Field(default_factory=list)
    agents: list[BundleAgent] = Field(default_factory=list)
    channels: list[BundleChannel] = Field(default_factory=list)
    automations: list[BundleAutomation] = Field(default_factory=list)
    policies: list[BundlePolicy] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version '{v}'; expected '{SCHEMA_VERSION}'")
        return v

    def setup_field(self, key: str) -> SetupField | None:
        return next((f for f in self.setup if f.key == key), None)
