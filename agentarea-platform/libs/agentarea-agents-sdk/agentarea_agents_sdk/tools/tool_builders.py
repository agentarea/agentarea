"""Per-tool-type build strategies (GoF Strategy + Registry).

Replaces the ``if tool_type == "code"/"mcp"/"agent"/"openapi"`` switch that used
to be duplicated across ``ToolManager._discover`` and
``ToolManager.discover_tool_providers``. Each tool type owns a builder that knows
how to turn its config into either flat OpenAI function definitions
(``add_explicit``) or a typed ``ToolProvider`` (``add_provider``). ``ToolManager``
holds a ``{type: builder}`` registry and dispatches by lookup.

Builders reuse ``ToolManager``'s discovery helpers via ``ctx.manager`` rather than
re-importing it (keeps the dependency one-way: manager -> builders).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from .agent_tool_factory import AgentToolFactory
from .code_tools_loader import create_code_tool_instance
from .decorator_tool import Toolset, ToolsetAdapter
from .tool_provider import (
    AgentToolProvider,
    CodeToolProvider,
    MCPToolProvider,
    OpenAPIToolProvider,
    ToolProvider,
)

if TYPE_CHECKING:
    from .tool_manager import DiscoveryResult, ToolManager

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """A single agent tool config, normalized: name + its settings bag."""

    name: str
    settings: dict[str, Any]


@dataclass
class ToolBuildContext:
    """Everything a builder needs that isn't on the spec itself.

    ``manager`` is the owning ``ToolManager`` — builders call its shared
    discovery helpers (``_discover_mcp_tools_by_name`` etc.) through it.
    """

    manager: ToolManager
    mcp_server_instance_service: Any
    agent_service: Any | None = None
    base_url: str = ""
    auth_token: str | None = None
    task_service: Any = None
    workspace_id: str | None = None
    user_id: str | None = None
    force_explicit: bool = True


def _allowed_tool_names(settings: dict[str, Any]) -> list[str]:
    """Flatten ``allowed_tools`` (strings or {tool_name,...} objects) to names."""
    raw = settings.get("allowed_tools") or []
    return [str(t["tool_name"] if isinstance(t, dict) else t) for t in raw]


class ToolBuilder(ABC):
    """Strategy: build the tools for one agent-tool ``type``."""

    type: ClassVar[str]

    @abstractmethod
    async def _tool_defs(self, spec: ToolSpec, ctx: ToolBuildContext) -> list[dict[str, Any]]:
        """Resolve this tool into OpenAI function definitions (may be empty)."""

    @abstractmethod
    def _provider(
        self, spec: ToolSpec, ctx: ToolBuildContext, defs: list[dict[str, Any]]
    ) -> ToolProvider:
        """Wrap resolved defs into this type's ToolProvider."""

    async def add_explicit(
        self, spec: ToolSpec, ctx: ToolBuildContext, result: DiscoveryResult
    ) -> None:
        result.explicit_tools.extend(await self._tool_defs(spec, ctx))

    async def add_provider(
        self, spec: ToolSpec, ctx: ToolBuildContext, providers: list[ToolProvider]
    ) -> None:
        defs = await self._tool_defs(spec, ctx)
        if defs:
            providers.append(self._provider(spec, ctx, defs))


class CodeToolBuilder(ToolBuilder):
    type = "code"

    async def _tool_defs(self, spec: ToolSpec, ctx: ToolBuildContext) -> list[dict[str, Any]]:
        disabled = spec.settings.get("disabled_methods", [])
        toolset_methods = {method: False for method in disabled} if disabled else {}
        instance = create_code_tool_instance(spec.name, toolset_methods)
        if not instance:
            logger.warning("Unknown code tool requested: %s", spec.name)
            return []
        if isinstance(instance, Toolset):
            instance = ToolsetAdapter(instance)
        logger.info("Added code tool: %s", spec.name)
        return [instance.get_openai_function_definition()]

    def _provider(self, spec, ctx, defs):
        return CodeToolProvider(name=spec.name, tools=defs)


class McpToolBuilder(ToolBuilder):
    type = "mcp"

    async def _tool_defs(self, spec: ToolSpec, ctx: ToolBuildContext) -> list[dict[str, Any]]:
        tools = await ctx.manager._discover_mcp_tools_by_name(
            spec.name, _allowed_tool_names(spec.settings), ctx.mcp_server_instance_service
        )
        return [t.get_openai_function_definition() for t in tools]

    def _provider(self, spec, ctx, defs):
        return MCPToolProvider(name=spec.name, instance_id="", tools=defs)


class AgentToolBuilder(ToolBuilder):
    type = "agent"

    async def _tool_defs(self, spec: ToolSpec, ctx: ToolBuildContext) -> list[dict[str, Any]]:
        if not ctx.agent_service or not ctx.base_url:
            logger.warning(
                "Skipping agent tool '%s': agent_service or base_url not provided", spec.name
            )
            return []
        tool = await AgentToolFactory.create_tool(
            agent_name=spec.name,
            agent_service=ctx.agent_service,
            base_url=ctx.base_url,
            a2a_url_override=spec.settings.get("a2a_url"),
            auth_token=ctx.auth_token,
            description_override=spec.settings.get("description_override"),
            task_service=ctx.task_service,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user_id,
        )
        if not tool:
            return []
        logger.info("Added agent tool: %s", spec.name)
        return [tool.get_openai_function_definition()]

    def _provider(self, spec, ctx, defs):
        return AgentToolProvider(name=spec.name, agent_id="", tools=defs)


class OpenApiToolBuilder(ToolBuilder):
    type = "openapi"

    @staticmethod
    def _connection_ref(spec: ToolSpec) -> str:
        # Prefer the stable UUID so renaming a connection doesn't break the link.
        return spec.settings.get("openapi_connection_id") or spec.name

    async def _tool_defs(self, spec: ToolSpec, ctx: ToolBuildContext) -> list[dict[str, Any]]:
        tools = await ctx.manager._discover_openapi_tools_by_name(
            self._connection_ref(spec),
            _allowed_tool_names(spec.settings),
            ctx.manager._openapi_connection_service,
        )
        return [t.get_openai_function_definition() for t in tools]

    async def add_explicit(self, spec, ctx, result) -> None:
        load_mode = spec.settings.get("load_mode")
        if load_mode == "searchable" and not ctx.force_explicit:
            entries = await ctx.manager._build_openapi_searchable_entries(
                self._connection_ref(spec),
                _allowed_tool_names(spec.settings),
                ctx.manager._openapi_connection_service,
            )
            result.searchable_entries.extend(entries)
        else:
            result.explicit_tools.extend(await self._tool_defs(spec, ctx))

    def _provider(self, spec, ctx, defs):
        return OpenAPIToolProvider(
            name=spec.name, connection_id=str(self._connection_ref(spec)), tools=defs
        )


def build_tool_builder_registry() -> dict[str, ToolBuilder]:
    """The {type: builder} registry ToolManager dispatches through."""
    builders: list[ToolBuilder] = [
        CodeToolBuilder(),
        McpToolBuilder(),
        AgentToolBuilder(),
        OpenApiToolBuilder(),
    ]
    return {b.type: b for b in builders}


def parse_tool_spec(tool: dict[str, Any]) -> ToolSpec | None:
    """Normalize a raw tool config dict to a ToolSpec, or None if unusable."""
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        logger.warning("Skipping tool with missing name", extra={"tool_config": tool})
        return None
    settings = tool.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    return ToolSpec(name=name, settings=settings)
