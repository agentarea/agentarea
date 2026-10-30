"""AgentsToolset — manage agents in the workspace.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth is the Pydantic DTO ``AgentCreate``/``AgentUpdate``
in ``agentarea_agents.schemas.dto``. The contract test in
``tests/contracts/test_mcp_rest_parity.py`` enforces parity.
"""

import builtins
import json
from typing import Annotated, Any, cast
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService, ReasoningConflictError
from agentarea_agents.schemas.dto import (
    REASONING_EFFORT_DESCRIPTION,
    REASONING_MAX_TOKENS_DESCRIPTION,
    AgentCreate,
    AgentTypeLiteral,
    AgentUpdate,
)
from agentarea_agents.schemas.import_export import ToolConfig
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.agent_status import AgentArchivedError
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.di.container import resolve
from fastapi import HTTPException
from pydantic import BaseModel, Field, TypeAdapter
from pydantic.experimental.missing_sentinel import MISSING

from ..api.v1._agent_tools import validate_code_tool_names
from .base import platform_context, platform_read_context

_TOOL_LIST = TypeAdapter(list[ToolConfig])

_AGENT_ID = "Agent id (UUID), from `agents_list` or `agents_create`."
_TOOLS = (
    'Tool configs, each {"type": "code"|"mcp"|"agent"|"openapi", "name": str, '
    '"settings"?: object}. Built-in toolsets are {"type": "code", "name": "agentarea/shell"}; '
    "an MCP server is its instance name with type mcp."
)


class AgentSummaryOutput(BaseModel):
    id: str = Field(description="Agent id (UUID).")
    name: str = Field(description="Agent name.")
    description: str | None = Field(default=None, description="Short summary of the agent.")


class AgentDetailOutput(AgentSummaryOutput):
    model_id: str | None = Field(
        default=None, description="Model instance id the agent runs on; null when none is bound."
    )
    instruction: str | None = Field(default=None, description="The agent's system prompt.")
    agent_type: str = Field(description="stateless or stateful.")
    reasoning_effort: str | None = Field(default=None, description=REASONING_EFFORT_DESCRIPTION)
    reasoning_max_tokens: int | None = Field(
        default=None, description=REASONING_MAX_TOKENS_DESCRIPTION
    )


class AgentRefOutput(BaseModel):
    id: str = Field(description="Agent id (UUID).")
    name: str = Field(description="Agent name.")


class AgentArchivedOutput(BaseModel):
    archived: bool = Field(description="False when no such agent existed.")


class AgentRestoredOutput(BaseModel):
    restored: bool = Field(description="False when no such agent existed.")


def _build_service(repo_factory, event_broker) -> AgentService:
    authz = resolve(AuthorizationService)
    return AgentService(repo_factory, event_broker, authorization_service=authz)


@toolset(
    namespace="agentarea/agents",
    display_name="Agent Management",
    description="Create, list, update, archive, and restore agents in the workspace.",
    category="platform",
    plane="build",
)
class AgentsToolset(Toolset):
    """Manage agents: list, get, create, update, archive, restore."""

    open_world = False

    @tool_method(
        display_name="List agents", effect="read", output=builtins.list[AgentSummaryOutput]
    )
    @enforced_in_handler("rows the graph says this caller may read; see readable_resource_ids")
    async def list(
        self,
        limit: Annotated[int, Field(description="Maximum number of agents to return.")] = 50,
        offset: Annotated[int, Field(description="Number of agents to skip, for paging.")] = 0,
    ) -> str:
        """List all agents in the workspace."""
        async with platform_read_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            agents = await service.list()
            readable = await readable_resource_ids(user_ctx)
            return json.dumps(
                [
                    {"id": str(a.id), "name": a.name, "description": a.description}
                    for a in agents
                    if str(a.id) in readable
                ],
                default=str,
            )

    @tool_method(display_name="Get agent", effect="read", output=AgentDetailOutput)
    @requires("read", "agent", id_param="agent_id")
    async def get(self, agent_id: Annotated[str, Field(description=_AGENT_ID)]) -> str:
        """Get agent details by ID."""
        async with platform_read_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            agent = await service.get(UUID(agent_id))
            if not agent:
                raise ToolError("Agent not found")
            return json.dumps(
                {
                    "id": str(agent.id),
                    "name": agent.name,
                    "description": agent.description,
                    "model_id": agent.model_id,
                    "instruction": agent.instruction,
                    "agent_type": agent.agent_type,
                    "reasoning_effort": agent.reasoning_effort,
                    "reasoning_max_tokens": agent.reasoning_max_tokens,
                },
                default=str,
            )

    @tool_method(display_name="Create agent", effect="write", output=AgentRefOutput)
    @unrestricted("any member may create an agent, as POST /v1/agents allows")
    async def create(
        self,
        name: Annotated[
            str, Field(description="Agent name, 1-255 characters, unique in the workspace.")
        ],
        model_id: Annotated[
            str,
            Field(
                description="Model instance id (UUID) the agent runs on, from `models_list_instances`."
            ),
        ],
        tools: Annotated[
            builtins.list[dict[str, Any]], Field(description=f"{_TOOLS} Pass [] for none.")
        ],
        description: Annotated[
            str, Field(description="Short summary of what the agent does, at most 1000 characters.")
        ] = "",
        instruction: Annotated[
            str, Field(description="System prompt for the agent, at most 20000 characters.")
        ] = "",
        agent_type: Annotated[
            AgentTypeLiteral,
            Field(
                description="stateful keeps conversation context across runs; "
                "stateless treats each run independently."
            ),
        ] = "stateless",
        reasoning_effort: Annotated[
            str | None, Field(description=REASONING_EFFORT_DESCRIPTION)
        ] = None,
        reasoning_max_tokens: Annotated[
            int | None, Field(description=REASONING_MAX_TOKENS_DESCRIPTION)
        ] = None,
    ) -> str:
        """Create a new agent.

        ``tools`` is required: pass [] for an agent with no tools. Built-in
        toolsets are ``{"type": "code", "name": "agentarea/shell"}``; GET
        /v1/agents/tools lists them.
        """
        payload = AgentCreate(
            name=name,
            description=description,
            instruction=instruction,
            model_id=model_id,
            tools=_TOOL_LIST.validate_python(tools),
            agent_type=agent_type,
            reasoning_effort=reasoning_effort,
            reasoning_max_tokens=reasoning_max_tokens,
        )
        try:
            validate_code_tool_names(payload.tools)
        except HTTPException as exc:
            raise ToolError(exc.detail) from exc
        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            agent = await service.create_agent(payload)
            return json.dumps({"id": str(agent.id), "name": agent.name}, default=str)

    @tool_method(
        display_name="Update agent", effect="write", idempotent=True, output=AgentRefOutput
    )
    @requires("edit", "agent", id_param="agent_id")
    async def update(
        self,
        agent_id: Annotated[str, Field(description=_AGENT_ID)],
        name: Annotated[
            str | None, Field(description="New agent name; omit to keep the current one.")
        ] = None,
        description: Annotated[
            str | None, Field(description="New summary; omit to keep the current one.")
        ] = None,
        instruction: Annotated[
            str | None, Field(description="New system prompt; omit to keep the current one.")
        ] = None,
        model_id: Annotated[
            str | None,
            Field(
                description="New model instance id, from `models_list_instances`; omit to keep it."
            ),
        ] = None,
        tools: Annotated[
            builtins.list[dict[str, Any]] | None,
            Field(description=f"{_TOOLS} Replaces the whole list; omit to keep the current tools."),
        ] = None,
        reasoning_effort: Annotated[
            str | None,
            Field(
                description=f"{REASONING_EFFORT_DESCRIPTION} Omit to keep the current setting; "
                'pass "" to go back to the model\'s default.'
            ),
        ] = None,
        reasoning_max_tokens: Annotated[
            int | None,
            Field(
                description=f"{REASONING_MAX_TOKENS_DESCRIPTION} Omit to keep the current "
                "setting; pass null to go back to the model's default."
            ),
        ] = cast(Any, MISSING),
    ) -> str:
        """Update an existing agent.

        ``tools`` replaces the agent's whole tool list, in the shape ``create``
        takes; leave it out to keep the tools as they are.
        """
        patch: dict[str, object] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if instruction is not None:
            patch["instruction"] = instruction
        if model_id is not None:
            patch["model_id"] = model_id
        if tools is not None:
            patch["tools"] = _TOOL_LIST.validate_python(tools)
        if reasoning_effort is not None:
            patch["reasoning_effort"] = reasoning_effort
        if reasoning_max_tokens is not MISSING:
            patch["reasoning_max_tokens"] = reasoning_max_tokens
        payload = AgentUpdate.model_validate(patch)
        try:
            validate_code_tool_names(payload.tools)
        except HTTPException as exc:
            raise ToolError(exc.detail) from exc

        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            try:
                agent = await service.update_agent(UUID(agent_id), payload)
            except (AgentArchivedError, ReasoningConflictError) as exc:
                raise ToolError(str(exc)) from exc
            if not agent:
                raise ToolError("Agent not found")
            return json.dumps({"id": str(agent.id), "name": agent.name}, default=str)

    @tool_method(
        display_name="Archive agent",
        effect="destructive",
        idempotent=True,
        output=AgentArchivedOutput,
    )
    @requires("delete", "agent", id_param="agent_id")
    async def archive(self, agent_id: Annotated[str, Field(description=_AGENT_ID)]) -> str:
        """Archive an agent by ID.

        It leaves the agent list, its triggers stop, and it takes no new runs;
        the runs it already made keep showing it. ``restore`` brings it back.
        """
        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            archived = await service.archive_agent(UUID(agent_id))
            return json.dumps({"archived": archived})

    @tool_method(
        display_name="Restore agent",
        effect="write",
        idempotent=True,
        output=AgentRestoredOutput,
    )
    @requires("delete", "agent", id_param="agent_id")
    async def restore(self, agent_id: Annotated[str, Field(description=_AGENT_ID)]) -> str:
        """Bring an archived agent back.

        A trigger that fired while the agent was archived was stopped then, and
        stays off until it is turned on again.
        """
        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            restored = await service.restore_agent(UUID(agent_id))
            return json.dumps({"restored": restored})
