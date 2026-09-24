"""A routed MCP call reaches its server only through an attachment that enables it.

Disclosure hides tools the agent was not given, but the model can still emit
any name. The tool activity is the last point before the server, so it checks
the call against the agent's own attachment rather than trusting disclosure.
"""

from uuid import uuid4

from agentarea_execution.activities.agent_execution_activities import mcp_route_denial
from agentarea_execution.models import McpToolRoute

GITHUB = str(uuid4())


def _route(raw_name: str = "search", attachment_ref: str = GITHUB) -> McpToolRoute:
    return McpToolRoute(instance_id=GITHUB, raw_name=raw_name, attachment_ref=attachment_ref)


def _attachment(allowed, ref: str = GITHUB) -> dict:
    return {"type": "mcp", "name": ref, "settings": {"allowed_tools": allowed}}


def test_all_tools_mode_admits_any_tool_of_the_server():
    assert mcp_route_denial([_attachment(None)], _route()) is None
    assert mcp_route_denial([{"type": "mcp", "name": GITHUB}], _route()) is None


def test_listed_tool_is_admitted():
    tools = [_attachment([{"tool_name": "search"}, {"tool_name": "create_issue"}])]
    assert mcp_route_denial(tools, _route()) is None


def test_unlisted_tool_is_refused():
    tools = [_attachment([{"tool_name": "create_issue"}])]
    assert mcp_route_denial(tools, _route()) == "the tool is not enabled for this agent"


def test_every_tool_switched_off_refuses_them_all():
    assert mcp_route_denial([_attachment([])], _route()) == "the tool is not enabled for this agent"


def test_server_the_agent_does_not_attach_is_refused():
    other = _attachment(None, ref=str(uuid4()))
    assert mcp_route_denial([other], _route()) == "its MCP server is not attached to this agent"
    assert mcp_route_denial(None, _route()) == "its MCP server is not attached to this agent"


def test_attachment_by_name_is_matched_by_its_own_reference():
    tools = [_attachment([{"tool_name": "search"}], ref="github")]
    assert mcp_route_denial(tools, _route(attachment_ref="github")) is None
