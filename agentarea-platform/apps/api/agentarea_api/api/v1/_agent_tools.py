"""Checks on the tools an agent is given, shared by the REST routes and the MCP tools."""

from agentarea_agents.schemas.import_export import ToolConfig
from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata
from fastapi import HTTPException


def validate_code_tool_names(tools: list[ToolConfig] | None) -> None:
    """Refuse code tool configs that name no registered toolset.

    Such a config builds nothing, but its name would still reach policy as a
    name of the agent's tools.
    """
    if not tools:
        return
    available_code_tools = get_code_tools_metadata()
    invalid_tools = [
        tool_config.name
        for tool_config in tools
        if tool_config.type == "code" and tool_config.name not in available_code_tools
    ]
    if invalid_tools:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid code tools: {invalid_tools}. "
                f"Available tools: {list(available_code_tools.keys())}"
            ),
        )
