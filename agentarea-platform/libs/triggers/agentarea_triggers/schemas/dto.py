"""Trigger CRUD DTOs — single source of truth for REST, MCP toolset, and service layer.

These models live in the trigger library (not the API app) so the toolset
in ``apps/api/agentarea_api/tools`` and the service in this lib can both
import them without layering inversion. Field descriptions are written for
LLM consumers (they end up in the MCP tool schema) but are equally suitable
for REST clients reading the OpenAPI doc.

The ``agentarea_triggers.domain.models.TriggerCreate`` /
``TriggerUpdate`` value objects are the internal service-input shape
(they carry server-derived ``created_by`` / ``workspace_id``). Use
``TriggerCreate.to_domain(...)`` / ``TriggerUpdate.to_domain(...)`` to
convert.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from agentarea_common.model_override import check_model_override
from agentarea_common.reasoning_effort import check_reasoning_effort
from agentarea_common.reserved_task_parameters import (
    drop_reserved_parameters,
    reject_reserved_parameters,
)
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import TriggerBatchWindow, TriggerSession
from agentarea_triggers.domain.models import (
    TriggerCreate as _DomainTriggerCreate,
)
from agentarea_triggers.domain.models import (
    TriggerUpdate as _DomainTriggerUpdate,
)

TriggerTypeLiteral = Literal["cron", "stream"]


class TriggerSpec(BaseModel):
    """Everything about a trigger except the agent it fires.

    A trigger fires an agent — on a cron schedule (``trigger_type='cron'``) or on
    the events of a stream (``trigger_type='stream'``). A webhook or a polled
    provider is a source of a stream (``streams_create_source``) with a stream
    trigger on it. Creating an agent takes a list of these, because the agent
    does not exist yet when they are written.
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
    trigger_type: TriggerTypeLiteral = Field(
        description=(
            "'cron' for scheduled, 'stream' to run on the events of a stream (a webhook or "
            "a polled provider is a source of a stream)."
        ),
    )
    task_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters merged into the task created when the trigger fires.",
    )
    task_definition_id: UUID | None = Field(
        default=None,
        description=(
            "Saved task the trigger runs, of the same agent: its text and parameters are "
            "what each firing asks, in place of task_parameters."
        ),
    )
    conditions: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional conditions evaluated against event data before firing. An LLM "
            'condition ({"type": "llm", "description": ...}) must name the chat or '
            'decision model instance that evaluates it in "model_id"; each sub-condition '
            "of a combined condition names its own."
        ),
    )
    _reject_reserved_parameters = field_validator("task_parameters")(reject_reserved_parameters)
    _check_model_override = field_validator("task_parameters")(check_model_override)
    _check_reasoning_effort = field_validator("task_parameters")(check_reasoning_effort)
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

    # Stream-specific
    stream_id: UUID | None = Field(
        default=None,
        description="Stream whose events fire this trigger (required when trigger_type='stream').",
    )
    event_filter: dict[str, Any] | None = Field(
        default=None,
        description=(
            'Which events of the stream fire it: {"kinds": ["push"], "fields": {"raw_data.action": '
            '"opened"}}. Empty means every event.'
        ),
    )

    session: TriggerSession | None = Field(
        default=None,
        description=(
            'What the next event of the same session does: {"continue": true, '
            '"idle_timeout": "30m"} joins the running task. Null takes the source '
            "type's default."
        ),
    )

    batch: TriggerBatchWindow | None = Field(
        default=None,
        description=(
            'Fire once for a batch of events instead of once per event: {"window": "1h", '
            '"max_events": 50} fires when the hour has passed or 50 events joined, '
            "whichever comes first. Null fires on every event."
        ),
    )

    @field_validator("trigger_type", mode="before")
    @classmethod
    def _normalize_trigger_type(cls, v: Any) -> Any:
        if isinstance(v, str):
            normalized = v.lower()
            valid = {"cron", "stream"}
            if normalized not in valid:
                # Friendly message for REST clients instead of the Literal's
                # auto-message, which leaks Pydantic phrasing.
                raise ValueError(f"Invalid trigger type: {v!r}. Must be one of: {sorted(valid)}")
            return normalized
        return v

    @model_validator(mode="after")
    def _require_type_fields(self) -> TriggerSpec:
        if self.trigger_type == "cron" and not self.cron_expression:
            raise ValueError("cron_expression is required when trigger_type is 'cron'")
        if self.trigger_type == "cron" and self.batch is not None:
            raise ValueError("only a stream trigger takes a batch")
        if self.trigger_type == "stream" and not self.stream_id:
            raise ValueError("stream_id is required when trigger_type is 'stream'")
        return self

    def to_domain_for(
        self, agent_id: UUID, created_by: str, workspace_id: str | None = None
    ) -> _DomainTriggerCreate:
        """Build the internal domain ``TriggerCreate`` for ``agent_id``."""
        domain_obj = _DomainTriggerCreate(
            name=self.name,
            description=self.description,
            agent_id=agent_id,
            trigger_type=TriggerType(self.trigger_type),
            task_parameters=self.task_parameters,
            task_definition_id=self.task_definition_id,
            conditions=self.conditions,
            created_by=created_by,
            is_active=self.enabled,
            failure_threshold=self.failure_threshold,
            cron_expression=self.cron_expression,
            timezone=self.timezone,
            stream_id=self.stream_id,
            event_filter=self.event_filter,
            session=self.session,
            batch=self.batch,
        )
        # Workspace id is server-assigned and may be ``None`` until auth resolves.
        # Set post-construction so callers can pass through ad-hoc values
        # (test fixtures, system contexts) without re-validating.
        domain_obj.workspace_id = workspace_id
        return domain_obj


class TriggerCreate(TriggerSpec):
    """Payload for creating a trigger on an existing agent."""

    agent_id: UUID = Field(
        description="UUID of the agent to invoke when the trigger fires.",
    )

    def to_domain(self, created_by: str, workspace_id: str | None = None) -> _DomainTriggerCreate:
        """Build the internal domain ``TriggerCreate`` value object."""
        return self.to_domain_for(self.agent_id, created_by, workspace_id)


class TriggerUpdate(BaseModel):
    """Patch payload for a trigger. All fields optional — unset = unchanged."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    agent_id: UUID | None = None
    enabled: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("enabled", "is_active"),
        description=(
            "Toggle the trigger active state. Maps to ``is_active`` server-side. "
            "REST clients may pass either ``enabled`` (canonical) or ``is_active`` (alias)."
        ),
    )
    task_parameters: dict[str, Any] | None = None
    task_definition_id: UUID | None = Field(
        default=None,
        description="Sent as null, the trigger asks its own task_parameters text again.",
    )
    conditions: dict[str, Any] | None = None
    failure_threshold: int | None = Field(default=None, ge=1, le=100)
    _drop_reserved_parameters = field_validator("task_parameters")(drop_reserved_parameters)

    cron_expression: str | None = None
    timezone: str | None = None

    event_filter: dict[str, Any] | None = None
    session: TriggerSession | None = None
    batch: TriggerBatchWindow | None = Field(
        default=None, description="Sent as null, the trigger fires on every event again."
    )

    def to_domain(self) -> _DomainTriggerUpdate:
        """Build the internal domain ``TriggerUpdate`` value object."""
        # Sent as null, these go back to the defaults; left out, they stay.
        kept: dict[str, Any] = {
            field: getattr(self, field)
            for field in ("session", "batch", "task_definition_id")
            if field in self.model_fields_set
        }
        return _DomainTriggerUpdate(
            name=self.name,
            description=self.description,
            agent_id=self.agent_id,
            is_active=self.enabled,
            task_parameters=self.task_parameters,
            conditions=self.conditions,
            failure_threshold=self.failure_threshold,
            cron_expression=self.cron_expression,
            timezone=self.timezone,
            event_filter=self.event_filter,
            **kept,
        )
