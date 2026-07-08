"""Trigger CRUD DTOs — single source of truth for REST, MCP toolset, and service layer.

These models live in the trigger library (not the API app) so the toolset
in ``apps/api/agentarea_api/tools`` and the service in this lib can both
import them without layering inversion. Field descriptions are written for
LLM consumers (they end up in the MCP tool schema) but are equally suitable
for REST clients reading the OpenAPI doc.

The legacy ``agentarea_triggers.domain.models.TriggerCreate`` /
``TriggerUpdate`` value objects remain as the internal service-input shape
(they carry server-derived ``created_by`` / ``workspace_id``). Use
``TriggerCreate.to_domain(...)`` / ``TriggerUpdate.to_domain(...)`` to
convert.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from agentarea_triggers.domain.channel_events import CHANNEL_EVENTS
from agentarea_triggers.domain.enums import TriggerType, WebhookType
from agentarea_triggers.domain.models import (
    TriggerCreate as _DomainTriggerCreate,
)
from agentarea_triggers.domain.models import (
    TriggerUpdate as _DomainTriggerUpdate,
)

TriggerTypeLiteral = Literal["cron", "webhook", "polling"]


class TriggerCreate(BaseModel):
    """Payload for creating a trigger.

    A trigger fires an agent — either on a cron schedule (``trigger_type='cron'``)
    or in response to an inbound webhook (``trigger_type='webhook'``). For poll-based
    channels (e.g. email inbox), use ``trigger_type='polling'`` plus a
    ``data_extractor`` configuration.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable trigger name.",
    )
    description: str = Field(
        default="",
        max_length=1000,
        description="Short summary of what this trigger does.",
    )
    agent_id: UUID = Field(
        description="UUID of the agent to invoke when the trigger fires.",
    )
    trigger_type: TriggerTypeLiteral = Field(
        description="'cron' for scheduled, 'webhook' for inbound HTTP, 'polling' for extractor-driven.",
    )
    task_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters merged into the task created when the trigger fires.",
    )
    conditions: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional conditions evaluated against event data before firing.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the trigger is active immediately on creation.",
    )

    failure_threshold: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Auto-disable after this many consecutive failed executions.",
    )

    # Cron-specific
    cron_expression: str | None = Field(
        default=None,
        description="5- or 6-field cron expression (required when trigger_type='cron').",
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone for cron evaluation (e.g. 'UTC', 'America/New_York').",
    )
    data_extractor: str | None = Field(
        default=None,
        description="Polling extractor identifier (e.g. 'imap', 'rss').",
    )
    data_extractor_config: dict[str, Any] | None = Field(
        default=None,
        description="Connection/auth details for the polling extractor.",
    )

    # Webhook-specific
    webhook_id: str | None = Field(
        default=None,
        description="Public webhook path segment. Auto-generated if omitted for webhook triggers.",
    )
    allowed_methods: list[str] = Field(
        default_factory=lambda: ["POST"],
        description="HTTP methods accepted on the webhook endpoint.",
    )
    webhook_type: str = Field(
        default="generic",
        description="Channel type: 'generic', 'telegram', 'slack', 'discord', etc.",
    )
    validation_rules: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-channel validation rules (signature secrets, allowed senders, etc).",
    )
    webhook_config: dict[str, Any] | None = Field(
        default=None,
        description="Channel-specific configuration (bot tokens, signing keys, etc).",
    )
    event_types: list[str] = Field(
        default_factory=list,
        description="Event types to filter on (empty list = accept all events).",
    )

    # Channel credentials — written to the secret store, never returned in responses
    channel_credentials: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Channel credentials (bot_token, SMTP password, etc). "
            "Stored encrypted in the secret store. Never returned in responses."
        ),
    )

    @field_validator("trigger_type", mode="before")
    @classmethod
    def _normalize_trigger_type(cls, v: Any) -> Any:
        if isinstance(v, str):
            normalized = v.lower()
            valid = {"cron", "webhook", "polling"}
            if normalized not in valid:
                # Friendly message preserved for REST clients (the Literal
                # auto-message would otherwise read "Input should be 'cron',
                # 'webhook' or 'polling'", which leaks Pydantic phrasing).
                raise ValueError(f"Invalid trigger type: {v!r}. Must be one of: {sorted(valid)}")
            return normalized
        return v

    @field_validator("webhook_type")
    @classmethod
    def _validate_webhook_type(cls, v: str) -> str:
        if not v:
            return v
        valid_types = list(CHANNEL_EVENTS.keys())
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid webhook type. Must be one of: {valid_types}")
        return v.lower()

    def to_domain(self, created_by: str, workspace_id: str | None = None) -> _DomainTriggerCreate:
        """Build the internal domain ``TriggerCreate`` value object.

        The auto-generated ``webhook_id`` (when omitted for webhook triggers)
        is handled here so callers don't have to repeat the logic.
        """
        if self.trigger_type == "cron":
            domain_type = TriggerType.CRON
        elif self.trigger_type == "polling":
            domain_type = TriggerType.POLLING
        else:
            domain_type = TriggerType.WEBHOOK

        webhook_id = self.webhook_id
        if domain_type == TriggerType.WEBHOOK and not webhook_id:
            import secrets

            webhook_id = secrets.token_urlsafe(16)

        domain_obj = _DomainTriggerCreate(
            name=self.name,
            description=self.description,
            agent_id=self.agent_id,
            trigger_type=domain_type,
            task_parameters=self.task_parameters,
            conditions=self.conditions,
            created_by=created_by,
            failure_threshold=self.failure_threshold,
            cron_expression=self.cron_expression,
            timezone=self.timezone,
            data_extractor=self.data_extractor,
            data_extractor_config=self.data_extractor_config,
            webhook_id=webhook_id,
            allowed_methods=self.allowed_methods,
            webhook_type=WebhookType(self.webhook_type),
            validation_rules=self.validation_rules,
            webhook_config=self.webhook_config,
            event_types=self.event_types,
        )
        # Workspace id is server-assigned and may be ``None`` until auth resolves.
        # Set post-construction so legacy callers can keep passing through ad-hoc
        # values (test fixtures, system contexts) without re-validating.
        domain_obj.workspace_id = workspace_id
        return domain_obj


class TriggerUpdate(BaseModel):
    """Patch payload for a trigger. All fields optional — unset = unchanged."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("enabled", "is_active"),
        description=(
            "Toggle the trigger active state. Maps to ``is_active`` server-side. "
            "REST clients may pass either ``enabled`` (canonical) or ``is_active`` (legacy)."
        ),
    )
    task_parameters: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None
    failure_threshold: int | None = Field(default=None, ge=1, le=100)

    cron_expression: str | None = None
    timezone: str | None = None

    allowed_methods: list[str] | None = None
    webhook_type: str | None = None
    validation_rules: dict[str, Any] | None = None
    webhook_config: dict[str, Any] | None = None

    channel_credentials: dict[str, Any] | None = Field(
        default=None,
        description="Channel credentials to update. Pass to rotate credentials.",
    )

    @field_validator("webhook_type")
    @classmethod
    def _validate_webhook_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid_types = list(CHANNEL_EVENTS.keys())
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid webhook type. Must be one of: {valid_types}")
        return v.lower()

    def to_domain(self) -> _DomainTriggerUpdate:
        """Build the internal domain ``TriggerUpdate`` value object."""
        webhook_type = WebhookType(self.webhook_type) if self.webhook_type else None
        return _DomainTriggerUpdate(
            name=self.name,
            description=self.description,
            is_active=self.enabled,
            task_parameters=self.task_parameters,
            conditions=self.conditions,
            failure_threshold=self.failure_threshold,
            cron_expression=self.cron_expression,
            timezone=self.timezone,
            allowed_methods=self.allowed_methods,
            webhook_type=webhook_type,
            validation_rules=self.validation_rules,
            webhook_config=self.webhook_config,
        )
