"""Contract test: ``GET /v1/agents/tools`` carries the toolset metadata it holds.

``get_code_tools_metadata()`` already knows each toolset's display name, category,
plane and tool methods. The endpoint used to drop all of it and return only
``name``/``description``, which forced the webapp to keep a hand-maintained mirror
of the registry to render a label, and left the per-method picker permanently
empty. Anything the catalog knows and the UI needs must survive the response
model, otherwise the mirror grows back.
"""

from __future__ import annotations

import pytest
from agentarea_api.api.v1.agents import get_all_tools

# Toolsets that make up an agent's own runtime, as opposed to the platform
# surface an agent uses to operate AgentArea itself.
RUNTIME_NAMESPACES = {
    "agentarea/math",
    "agentarea/files",
    "agentarea/workspace_files",
    "agentarea/context",
    "agentarea/web",
    "agentarea/shell",
}


async def _code_tools() -> dict[str, object]:
    tools = await get_all_tools(
        user_context=None,
        include="code",
        mcp_instance_id=None,
        mcp_service=None,
    )
    return {tool.name: tool for tool in tools}


@pytest.mark.asyncio
async def test_code_tools_carry_display_metadata() -> None:
    """A label the UI can render must come from the API, not a frontend map."""
    tools = await _code_tools()
    assert tools, "no code tools returned"

    missing = [name for name, tool in tools.items() if not tool.display_name]
    assert not missing, f"toolsets returned without a display_name: {sorted(missing)}"


@pytest.mark.asyncio
async def test_code_tools_carry_plane() -> None:
    """``plane`` is the axis the UI splits capabilities from platform access on."""
    tools = await _code_tools()

    for namespace in RUNTIME_NAMESPACES:
        assert namespace in tools, f"{namespace} missing from the code tools catalog"
        assert tools[namespace].plane == "runtime", (
            f"{namespace}: plane={tools[namespace].plane!r}, expected 'runtime'"
        )

    platform = [t for name, t in tools.items() if name not in RUNTIME_NAMESPACES]
    assert platform, "no platform toolsets in the catalog"
    assert all(t.plane and t.plane != "runtime" for t in platform), (
        "platform toolsets must declare a non-runtime plane: "
        f"{sorted(t.name for t in platform if not t.plane or t.plane == 'runtime')}"
    )


@pytest.mark.asyncio
async def test_code_tools_expose_their_methods() -> None:
    """The per-method picker needs the methods and what each one does."""
    tools = await _code_tools()
    shell = tools["agentarea/shell"]

    assert [m.name for m in shell.available_methods] == ["bash"]
    assert shell.available_methods[0].effect == "destructive"

    files = tools["agentarea/files"]
    assert len(files.available_methods) > 1, "file toolset should expose several methods"
    assert all(m.effect for m in files.available_methods), (
        "every exposed method must declare its effect"
    )
