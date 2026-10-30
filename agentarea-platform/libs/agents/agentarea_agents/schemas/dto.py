"""Agent CRUD DTOs — single source of truth for REST, MCP toolset, and service layer.

These models live in the domain library (not the API app) so the toolset
in ``apps/api/agentarea_api/tools`` and the service in this lib can both
import them without layering inversion. Field descriptions are written for
LLM consumers (they end up in the MCP tool schema) but are equally suitable
for REST clients reading the OpenAPI doc.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from agentarea_common.reasoning_effort import (
    checked_reasoning_effort,
    checked_reasoning_max_tokens,
)
from agentarea_common.utils.types import NotNull
from agentarea_governance.domain.policies import AnswerCheckPolicy
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentarea_agents.schemas.import_export import ToolConfig

AgentTypeLiteral = Literal["stateless", "stateful"]

REASONING_EFFORT_DESCRIPTION = (
    "A reasoning level the model takes, e.g. low or high; the catalog lists each "
    "model's levels. Unset keeps the model's default. Not together with reasoning_max_tokens."
)
REASONING_MAX_TOKENS_DESCRIPTION = (
    "A token budget for the model's reasoning, a positive integer. Unset keeps the "
    "model's default. Not together with reasoning_effort."
)


class AgentCreate(BaseModel):
    """Payload for creating an agent.

    ``model_id`` is the UUID of a model instance configured in the workspace —
    the runtime has no other interpretation of it. Omit it (or pass ``null``) to
    create an agent with no model bound yet; such an agent cannot be run until a
    model is assigned.
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
    model_id: str | None = Field(
        default=None,
        description=(
            "UUID of a model instance in this workspace (see GET /v1/model-instances). "
            "Null means no model is bound yet and the agent cannot be run."
        ),
    )
    tools: list[ToolConfig] = Field(
        description=(
            "Tools attached to the agent (code/mcp/agent/openapi). Required: pass [] "
            "for an agent with no tools. Built-in toolsets and their groups are "
            "listed by GET /v1/agents/tools."
        ),
    )
    planning: bool | None = Field(
        default=None,
        description="Enable explicit planning step before execution.",
    )
    a2ui_enabled: bool | None = Field(
        default=None,
        description="Expose this agent over the A2UI protocol.",
    )
    reasoning_effort: str | None = Field(
        default=None,
        description=REASONING_EFFORT_DESCRIPTION,
    )
    reasoning_max_tokens: int | None = Field(
        default=None,
        description=REASONING_MAX_TOKENS_DESCRIPTION,
    )
    answer_check: AnswerCheckPolicy | None = Field(
        default=None,
        description=(
            "Check the agent's final answer for leaks (other scripts, tool names, codes, "
            "JSON, stack traces) and have the model rewrite it once before the person "
            "sees it. Null leaves it off. A governance safety rule that sets "
            "answer_check overrides this setting."
        ),
    )
    skill_ids: list[UUID] | None = Field(
        default=None,
        description="UUIDs of skills to attach to the agent.",
    )
    agent_type: AgentTypeLiteral = Field(
        default="stateless",
        deprecated=True,
        description=(
            "DEPRECATED — stored and echoed back, but the runtime never reads it, "
            "so every agent behaves as 'stateless' regardless of this value. "
            "Conversation history does not currently survive across runs. Do not "
            "branch on this field."
        ),
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def _check_reasoning_effort(cls, v: object) -> str | None:
        return checked_reasoning_effort(v)

    @field_validator("reasoning_max_tokens", mode="before")
    @classmethod
    def _check_reasoning_max_tokens(cls, v: object) -> int | None:
        return checked_reasoning_max_tokens(v)

    @model_validator(mode="after")
    def _one_reasoning_form(self) -> AgentCreate:
        if self.reasoning_effort and self.reasoning_max_tokens:
            raise ValueError("set reasoning_effort or reasoning_max_tokens, not both")
        return self


class AgentUpdate(BaseModel):
    """Patch payload for an agent. All fields optional — unset = unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, NotNull] = Field(default=None, min_length=1, max_length=255)
    capabilities: list[str] | None = None
    description: str | None = Field(default=None, max_length=1000)
    instruction: str | None = Field(default=None, max_length=20000)
    model_id: str | None = None
    tools: list[ToolConfig] | None = None
    planning: bool | None = None
    a2ui_enabled: bool | None = None
    reasoning_effort: str | None = Field(default=None, description=REASONING_EFFORT_DESCRIPTION)
    reasoning_max_tokens: int | None = Field(
        default=None, description=REASONING_MAX_TOKENS_DESCRIPTION
    )
    answer_check: AnswerCheckPolicy | None = None
    skill_ids: list[UUID] | None = None
    agent_type: Annotated[AgentTypeLiteral | None, NotNull] = None

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def _check_reasoning_effort(cls, v: object) -> str | None:
        return checked_reasoning_effort(v)

    @field_validator("reasoning_max_tokens", mode="before")
    @classmethod
    def _check_reasoning_max_tokens(cls, v: object) -> int | None:
        return checked_reasoning_max_tokens(v)


class AgentSummary(BaseModel):
    """Lightweight agent reference returned by list/create-style tools."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
