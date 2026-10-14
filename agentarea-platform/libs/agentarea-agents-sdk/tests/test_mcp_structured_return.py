"""A toolset method that returns a dict is served over MCP as the JSON text it becomes.

No ``from __future__ import annotations`` here on purpose: the return annotation has to
be a real type, which is what made the SDK derive an output schema from it and refuse
the serialized result.
"""

import json
from typing import Any

from agentarea_agents_sdk.mcp_server import create_mcp_server
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import ToolsetMetadata


class _QuoteToolset(Toolset):
    # Metadata without @toolset: registering would leak into the global catalog.
    __toolset_meta__ = ToolsetMetadata(namespace="test/quotes")

    @tool_method
    async def quote(self, symbol: str) -> dict[str, Any]:
        """Quote a symbol."""
        return {"success": True, "result": symbol, "platform_cost": "0.03"}


async def test_a_dict_result_reaches_the_caller_as_json_text():
    server = create_mcp_server(toolsets=[_QuoteToolset()], name="Test", workspace_argument=False)

    result = await server.call_tool_result("quotes_quote", {"symbol": "YNDX"})

    assert not result.is_error
    assert json.loads(result.content[0].text) == {
        "success": True,
        "result": "YNDX",
        "platform_cost": "0.03",
    }
