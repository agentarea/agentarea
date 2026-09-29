"""Serve a stdio MCP server over Streamable HTTP for both protocol eras.

The child starts once and is initialized once, with the handshake stdio
servers speak. The HTTP port opens only after that succeeded, so a listening
port means a working MCP server, not a spawned process. Outward the SDK serves
2026-07-28 and 2025 clients from one endpoint and mints no sessions; every
request is forwarded to the one child.

The process exits, taking the container with it, when the child does not
initialize within the startup timeout or stops running afterwards: a port
that answers every request with an error helps nobody.

The child is a single process with its own state, so an instance served this
way runs as one replica. Server-initiated requests from the child (sampling,
elicitation, roots) are not forwarded: a stateless endpoint has no channel
back to the caller.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import anyio
import uvicorn
from mcp import Client, MCPError, StdioServerParameters
from mcp.server import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CONNECTION_CLOSED,
    CallToolRequestParams,
    CallToolResult,
    CompleteRequestParams,
    CompleteResult,
    GetPromptRequestParams,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
)
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from . import MCP_PATH

logger = logging.getLogger("mcp-base.stdio")

CHILD_PING_INTERVAL_SECONDS = 15.0


class ChildExitedError(RuntimeError):
    """The stdio server stopped running."""


class StartupTimeoutError(RuntimeError):
    """The stdio server did not finish initializing in time."""


def _forwarding_handlers(child: Client) -> dict[str, Callable[..., Awaitable[Any]]]:
    """One forwarding handler per capability the child declared, and no more.

    The low-level server advertises a capability for every handler it has,
    so registering one the child lacks would promise a feature nobody serves.
    """
    capabilities = child.server_capabilities
    if capabilities is None:
        raise ChildExitedError("the stdio server reported no capabilities")
    handlers: dict[str, Callable[..., Awaitable[Any]]] = {}

    if capabilities.tools is not None:

        async def list_tools(
            _ctx: object, params: PaginatedRequestParams | None
        ) -> ListToolsResult:
            return await child.list_tools(
                cursor=params.cursor if params else None, cache_mode="bypass"
            )

        async def call_tool(_ctx: object, params: CallToolRequestParams) -> CallToolResult:
            return await child.call_tool(params.name, params.arguments)

        handlers.update(on_list_tools=list_tools, on_call_tool=call_tool)

    if capabilities.resources is not None:

        async def list_resources(
            _ctx: object, params: PaginatedRequestParams | None
        ) -> ListResourcesResult:
            return await child.list_resources(
                cursor=params.cursor if params else None, cache_mode="bypass"
            )

        async def list_resource_templates(
            _ctx: object, params: PaginatedRequestParams | None
        ) -> ListResourceTemplatesResult:
            return await child.list_resource_templates(
                cursor=params.cursor if params else None, cache_mode="bypass"
            )

        async def read_resource(
            _ctx: object, params: ReadResourceRequestParams
        ) -> ReadResourceResult:
            return await child.read_resource(params.uri, cache_mode="bypass")

        handlers.update(
            on_list_resources=list_resources,
            on_list_resource_templates=list_resource_templates,
            on_read_resource=read_resource,
        )

    if capabilities.prompts is not None:

        async def list_prompts(
            _ctx: object, params: PaginatedRequestParams | None
        ) -> ListPromptsResult:
            return await child.list_prompts(
                cursor=params.cursor if params else None, cache_mode="bypass"
            )

        async def get_prompt(_ctx: object, params: GetPromptRequestParams) -> GetPromptResult:
            return await child.get_prompt(params.name, params.arguments)

        handlers.update(on_list_prompts=list_prompts, on_get_prompt=get_prompt)

    if capabilities.completions is not None:

        async def complete(_ctx: object, params: CompleteRequestParams) -> CompleteResult:
            return await child.complete(
                params.ref,
                {"name": params.argument.name, "value": params.argument.value},
                params.context.arguments if params.context else None,
            )

        handlers.update(on_completion=complete)

    return handlers


async def _health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


async def _watch_child(child: Client, http: uvicorn.Server) -> None:
    """End the bridge when the child is gone, but not when it is only busy.

    The ping carries no timeout and is never cancelled. A server that blocks
    its event loop — mcp-server-fetch runs `npm install` synchronously on its
    first fetch — answers late, and cancelling the late ping sends it a
    `notifications/cancelled` that 1.x Python servers crash on. A closed
    connection is the only evidence of death; a slow answer is not.
    """
    while not http.should_exit:
        await anyio.sleep(CHILD_PING_INTERVAL_SECONDS)
        try:
            # The session-level ping: Client.send_ping warns that ping is gone
            # in 2026-07-28, which is irrelevant to this legacy stdio session.
            await child.session.send_ping()
        except MCPError as exc:
            # Any answer, even an error, means the child is alive.
            if exc.code == CONNECTION_CLOSED:
                raise ChildExitedError("the stdio server exited") from exc
        except Exception as exc:
            raise ChildExitedError(f"the stdio server stopped running: {exc!r}") from exc


async def _startup_deadline(initialized: anyio.Event, timeout_seconds: float) -> None:
    with anyio.move_on_after(timeout_seconds):
        await initialized.wait()
        return
    raise StartupTimeoutError(f"the stdio server did not initialize within {timeout_seconds:.0f} s")


async def serve(
    command: Sequence[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str],
    port: int,
    startup_timeout_seconds: float,
) -> None:
    params = StdioServerParameters(
        command=command[0], args=list(command[1:]), env=dict(env), cwd=cwd
    )
    started = anyio.current_time()
    initialized = anyio.Event()
    # The deadline task returns as soon as the child initialized, so this group
    # only outlives it by the Client's lifetime; nothing here is cancelled at
    # shutdown, and the Client's own cleanup (terminating the child) runs
    # outside any cancelled scope.
    async with anyio.create_task_group() as startup:
        startup.start_soon(_startup_deadline, initialized, startup_timeout_seconds)
        async with Client(params, mode="legacy") as child:
            initialized.set()
            info = child.server_info
            logger.info(
                "stdio server %s initialized in %.0f ms (protocol %s)",
                info.name if info else command[0],
                (anyio.current_time() - started) * 1000,
                child.protocol_version,
            )
            server = Server(
                info.name if info else command[0],
                version=info.version if info else "",
                instructions=child.instructions,
                **_forwarding_handlers(child),
            )
            app = server.streamable_http_app(
                streamable_http_path=MCP_PATH,
                stateless_http=True,
                # The gateway in front owns Host validation; the container is
                # reached by an address the SDK's default allowlist cannot know.
                transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
                custom_starlette_routes=[Route("/health", _health)],
            )
            # All interfaces: the gateway reaches the container over its network.
            http = uvicorn.Server(
                uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")  # noqa: S104
            )
            async with anyio.create_task_group() as running:
                running.start_soon(_watch_child, child, http)
                await http.serve()
                running.cancel_scope.cancel()
