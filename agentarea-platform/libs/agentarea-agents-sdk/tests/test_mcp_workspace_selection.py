"""How an MCP tool call finds its workspace.

The bare mount spans workspaces, so each workspace-scoped tool takes a required
``workspace`` argument and runs bound to it. A pinned mount (``/mcp/w/<slug>``)
names the workspace in its URL and advertises no such argument. Either way the
reference goes through the REST membership gate.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agentarea_common.auth.context import UserPrincipal
from fastapi import FastAPI

from agentarea_agents_sdk.mcp_server import PinnedWorkspaceMiddleware, create_mcp_server
from agentarea_agents_sdk.mcp_server.auth import (
    PROTECTED_RESOURCE_SCOPE_KEY,
    WORKSPACE_SCOPE_KEY,
    WorkspaceAccessDeniedError,
    bind_workspace,
    get_mcp_user_context,
    use_mcp_user_context,
)
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method


class WhereToolset(Toolset):
    @tool_method
    async def where(self, note: str = "") -> str:
        """Report the workspace this call runs in."""
        return get_mcp_user_context().workspace_id


class UnscopedToolset(Toolset):
    workspace_scoped = False

    @tool_method
    async def whoami(self) -> str:
        """Report the caller."""
        return get_mcp_user_context().user_id


def _alice() -> UserPrincipal:
    return UserPrincipal(user_id="alice", accessible_workspaces=["ws-alice", "ws-acme"])


def _slugs(mapping: dict[str, str]):
    """Workspace rows: slug -> id."""

    async def load(*, workspace_id=None, slug=None):
        for row_slug, row_id in mapping.items():
            if slug == row_slug or workspace_id == row_id:
                return SimpleNamespace(id=row_id, slug=row_slug)
        return None

    return patch("agentarea_common.workspaces.lookup.load_workspace", new=load)


async def _tools(server) -> dict:
    return {tool.name: tool for tool in await server.list_tools()}


def _text(result) -> str:
    if hasattr(result, "content"):
        return result.content[0].text
    content = result[0] if isinstance(result, tuple) else result
    return content[0].text


class TestSchema:
    @pytest.mark.asyncio
    async def test_spanning_mount_requires_workspace(self):
        server = create_mcp_server(toolsets=[WhereToolset()], workspace_argument=True)

        schema = (await _tools(server))["where_where"].input_schema

        assert "workspace" in schema["properties"]
        assert "workspace" in schema["required"]
        assert "note" in schema["properties"]

    @pytest.mark.asyncio
    async def test_pinned_mount_has_no_workspace_argument(self):
        server = create_mcp_server(toolsets=[WhereToolset()], workspace_argument=False)

        schema = (await _tools(server))["where_where"].input_schema

        assert "workspace" not in schema["properties"]

    @pytest.mark.asyncio
    async def test_unscoped_toolset_opts_out(self):
        server = create_mcp_server(toolsets=[UnscopedToolset()], workspace_argument=True)

        schema = (await _tools(server))["unscoped_whoami"].input_schema

        assert "workspace" not in schema.get("properties", {})


class TestBinding:
    @pytest.mark.asyncio
    async def test_call_runs_in_the_named_workspace(self):
        server = create_mcp_server(toolsets=[WhereToolset()], workspace_argument=True)

        with use_mcp_user_context(_alice()), _slugs({"acme": "ws-acme"}):
            result = await server.call_tool("where_where", {"workspace": "acme"})

        assert _text(result) == "ws-acme"

    @pytest.mark.asyncio
    async def test_foreign_workspace_is_refused(self):
        server = create_mcp_server(toolsets=[WhereToolset()], workspace_argument=True)

        with use_mcp_user_context(_alice()), _slugs({"globex": "ws-globex"}):
            with pytest.raises(Exception) as exc:  # noqa: B017 - SDK wraps tool errors
                await server.call_tool("where_where", {"workspace": "globex"})
        assert isinstance(exc.value.__cause__, WorkspaceAccessDeniedError)

    @pytest.mark.asyncio
    async def test_missing_workspace_is_refused_not_defaulted(self):
        server = create_mcp_server(toolsets=[WhereToolset()], workspace_argument=True)

        with use_mcp_user_context(_alice()):
            with pytest.raises(Exception):  # noqa: B017 - FastMCP wraps the validation error
                await server.call_tool("where_where", {})

    @pytest.mark.asyncio
    async def test_binding_does_not_leak_into_the_caller(self):
        caller = _alice()

        with use_mcp_user_context(caller), _slugs({"acme": "ws-acme"}):
            async with bind_workspace("acme"):
                assert get_mcp_user_context().workspace_id == "ws-acme"
            assert get_mcp_user_context() is caller

        assert not hasattr(caller, "workspace_id")

    @pytest.mark.asyncio
    async def test_unknown_workspace_raises_permission_error(self):
        with use_mcp_user_context(_alice()), _slugs({}):
            with pytest.raises(WorkspaceAccessDeniedError):
                async with bind_workspace("nope"):
                    pass


class TestPinnedWorkspaceMiddleware:
    @staticmethod
    async def _scope_for(path: str) -> tuple[int, dict | None]:
        seen: dict = {}

        async def inner(scope, receive, send):
            seen.update(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        app = FastAPI()
        app.mount("/mcp/w", PinnedWorkspaceMiddleware(inner, prefix="/mcp/w"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(path, content=json.dumps({}))
        return response.status_code, (seen or None)

    @pytest.mark.asyncio
    async def test_workspace_is_pinned_from_the_path(self):
        status, scope = await self._scope_for("/mcp/w/acme")

        assert status == 200
        assert scope is not None
        assert scope[WORKSPACE_SCOPE_KEY] == "acme"
        assert scope[PROTECTED_RESOURCE_SCOPE_KEY] == "mcp/w/acme"
        assert scope["path"] == "/"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/mcp/w/", "/mcp/w/Acme", "/mcp/w/x%22,%20evil=%22y"])
    async def test_malformed_workspace_is_not_served(self, path):
        status, scope = await self._scope_for(path)

        assert status == 404
        assert scope is None


class TestSpanningMountServesNoBareTool:
    def test_base_tool_is_refused(self):
        from agentarea_agents_sdk.tools.base_tool import BaseTool

        class Bare(BaseTool):
            name = "bare"
            description = "Runs in whatever workspace the context holds."

            def get_schema(self):
                return {"parameters": {"type": "object", "properties": {}}}

            async def execute(self, **kwargs):
                return {"success": True, "result": "ok"}

        with pytest.raises(TypeError, match="workspace-spanning"):
            create_mcp_server(toolsets=[Bare()], workspace_argument=True)


class TestPinnedWorkspaceDenied:
    @pytest.mark.asyncio
    async def test_unreachable_pinned_workspace_is_403_not_401(self):
        """A 401 would send the client back into OAuth for the same token, forever."""
        from agentarea_agents_sdk.mcp_server.auth import MCPAuthMiddleware

        sent: list[dict] = []

        async def receive():
            return {
                "type": "http.request",
                "body": b'{"jsonrpc":"2.0","id":7,"method":"tools/list"}',
                "more_body": False,
            }

        async def send(message):
            sent.append(message)

        middleware = MCPAuthMiddleware(AsyncMock())
        with patch.object(MCPAuthMiddleware, "_try_authenticate", AsyncMock(return_value=True)):
            await middleware(
                {
                    "type": "http",
                    "path": "/",
                    "headers": [(b"authorization", b"Bearer t")],
                    WORKSPACE_SCOPE_KEY: "globex",
                    PROTECTED_RESOURCE_SCOPE_KEY: "mcp/w/globex",
                },
                receive,
                send,
            )

        start = next(m for m in sent if m["type"] == "http.response.start")
        body = json.loads(next(m for m in sent if m["type"] == "http.response.body")["body"])
        assert start["status"] == 403
        assert all(key != b"www-authenticate" for key, _ in start["headers"])
        assert body["error"]["message"] == "No accessible workspace 'globex'"
        assert body["id"] == 7
