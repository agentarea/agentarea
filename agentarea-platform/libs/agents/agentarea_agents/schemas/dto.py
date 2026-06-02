"""Agent CRUD DTOs — single source of truth for REST, MCP toolset, and service layer.

These models live in the domain library (not the API app) so the toolset
in ``apps/api/agentarea_api/tools`` and the service in this lib can both
import them without layering inversion. Field descriptions are written for
LLM consumers (they end up in the MCP tool schema) but are equally suitable
for REST clients reading the OpenAPI doc.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentarea_agents.schemas.import_export import ToolConfigYAML


class EventConfig(BaseModel):
    """One event subscription for an agent."""

    event_type: str = Field(description="Event type the agent listens to.")
    config: dict | None = Field(default=None, description="Event-specific configuration.")
    enabled: bool = Field(default=True, description="Whether this subscription is active.")


class EventsConfig(BaseModel):
    """Per-agent event subscriptions."""

    events: list[EventConfig] | None = None


AgentTypeLiteral = Literal["stateless", "stateful"]


class AgentCreate(BaseModel):
    """Payload for creating an agent.

    ``model_id`` accepts either a model-instance UUID configured in the
    workspace, or a recognized provider identifier (e.g. ``gpt-4o``,
    ``claude-3-5-sonnet``, ``openrouter/qwen/qwen-2.5-72b-instruct``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable agent name (unique per workspace).",
    )
    description: str = Field(
        default="",
        max_length=1000,
        description="Short summary of what the agent does.",
    )
    instruction: str = Field(
        default="",
        max_length=20000,
        description="System prompt / behavioural instructions for the agent.",
    )
    model_id: str = Field(
        description=(
            "Model instance UUID or provider model identifier (e.g. 'gpt-4o', 'claude-3-5-sonnet')."
        ),
    )
    tools: list[ToolConfigYAML] | None = Field(
        default=None,
        description="Tools attached to the agent (code/mcp/agent/openapi).",
    )
    events_config: EventsConfig | None = Field(
        default=None,
        description="Event subscriptions that auto-trigger this agent.",
    )
    planning: bool | None = Field(
        default=None,
        description="Enable explicit planning step before execution.",
    )
    a2ui_enabled: bool | None = Field(
        default=None,
        description="Expose this agent over the A2UI protocol.",
    )
    skill_ids: list[UUID] | None = Field(
        default=None,
        description="UUIDs of skills to attach to the agent.",
    )
    agent_type: AgentTypeLiteral = Field(
        default="stateless",
        description=(
            "'stateless' (each request independent) or 'stateful' "
            "(maintains conversation context across runs)."
        ),
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v


class AgentUpdate(BaseModel):
    """Patch payload for an agent. All fields optional — unset = unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    capabilities: list[str] | None = None
    description: str | None = Field(default=None, max_length=1000)
    instruction: str | None = Field(default=None, max_length=20000)
    model_id: str | None = None
    tools: list[ToolConfigYAML] | None = None
    events_config: EventsConfig | None = None
    planning: bool | None = None
    a2ui_enabled: bool | None = None
    skill_ids: list[UUID] | None = None
    agent_type: AgentTypeLiteral | None = None


class AgentSummary(BaseModel):
    """Lightweight agent reference returned by list/create-style tools."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
