"""Contract test: every platform MCP tool tells a client what it is, takes and returns.

A harness picks a tool, fills its arguments and reads its result from what the
server publishes alone: a title, a description of every argument, an output
schema, and whether the call reaches outside the platform. Checked on the
served tool list, the shape a client actually receives.
"""

from __future__ import annotations

import pytest
from agentarea_api.platform_mcp import create_platform_mcp_server

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def tools():
    server = create_platform_mcp_server(spanning=True)
    return await server.list_tools()


async def test_every_tool_has_a_title(tools) -> None:
    untitled = sorted(t.name for t in tools if not t.title)
    assert not untitled, f"Pass display_name=... to @tool_method: {untitled}"


async def test_every_argument_is_described(tools) -> None:
    bare = sorted(
        f"{t.name}.{name}"
        for t in tools
        for name, prop in t.input_schema.get("properties", {}).items()
        if not prop.get("description")
    )
    assert not bare, f"Annotate with Field(description=...): {bare}"


async def test_every_tool_publishes_its_output(tools) -> None:
    # A tool that declares no output still gets the SDK's {"result": string} wrapper.
    undeclared = sorted(
        t.name
        for t in tools
        if not t.output_schema
        or t.output_schema.get("properties", {}).get("result")
        == {"title": "Result", "type": "string"}
    )
    assert not undeclared, f"Pass output=... to @tool_method: {undeclared}"


async def test_every_tool_says_whether_it_reaches_outside(tools) -> None:
    undeclared = sorted(
        t.name for t in tools if t.annotations is None or t.annotations.open_world_hint is None
    )
    assert not undeclared, f"Set open_world on the toolset or on @tool_method: {undeclared}"
