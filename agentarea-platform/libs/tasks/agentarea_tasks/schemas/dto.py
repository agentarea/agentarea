"""Run / task DTOs — single source of truth for REST, MCP toolset, and service.

A "run" in product terminology is a single execution of an agent against a
user-supplied message. Internally it is persisted as a ``AgentTask`` and
driven by a Temporal workflow, but the public contract is intentionally
slimmer than the full task domain model: only the knobs callers (REST
clients, MCP tools, A2A peers) actually need to start a run live here.

Field descriptions are written for LLM consumers (they end up in the MCP
tool schema) but are equally suitable for REST clients reading the OpenAPI
doc.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from agentarea_governance.domain.policies import PolicyDocument
from pydantic import BaseModel, ConfigDict, Field


class RunExecutionConfig(BaseModel):
    """Caller-requested execution ceiling; governance may only tighten it."""

    model_config = ConfigDict(extra="forbid")

    max_model_turns: int = Field(
        gt=0,
        description="Maximum LLM/model turns requested for this run.",
    )


class RunCreate(BaseModel):
    """Payload for starting a new agent run.

    The ``agent_id`` field is part of the body (not just the REST path)
    so MCP/A2A callers — who don't have a path — can express it once.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID = Field(
        description="UUID of the agent that should execute this run.",
    )
    description: str = Field(
        min_length=1,
        max_length=20000,
        description=(
            "User-facing message / task description handed to the agent. "
            "Doubles as the run title and initial query when not overridden."
        ),
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Free-form task parameters. Recognized keys: "
            "``channel_origin`` (routes follow-ups to an existing workflow), "
            "``model_override`` (per-run model id), and any agent-specific "
            "context the workflow should see."
        ),
    )
    execution: RunExecutionConfig | None = Field(
        default=None,
        description=(
            "Typed execution request. The resolved value is capped by governance "
            "and persisted in the task governance snapshot."
        ),
    )
    requires_human_approval: bool = Field(
        default=False,
        description="Gate task execution on a human approval step before tool calls.",
    )
    project_id: str | None = Field(
        default=None,
        description="Optional project scope for billing / organization.",
    )
    package_install: Literal["allowed", "locked"] | None = Field(
        default=None,
        description=(
            "Sandbox managed-environment profile for this run. When omitted, "
            "the agent shell-tool setting is used, then defaults to 'allowed'."
        ),
    )
    task_policy: PolicyDocument | None = Field(
        default=None,
        description="Optional task-scoped governance policy that may only tighten higher scopes.",
    )
