#!/usr/bin/env python3
"""
MCP Bridge: Proxies stdio-based MCP servers over streamable-http.

Spawns a child process (npx, uvx, node, python, etc.) and exposes its
stdio-based MCP interface as a streamable-http endpoint at POST /mcp.

Usage:
    python bridge.py <command> [args...]
    python bridge.py npx -y @upstash/context7-mcp@latest
    python bridge.py uvx some-mcp-server
"""

import asyncio
import json
import logging
import os
import signal
import sys
import uuid

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="[mcp-bridge] %(message)s",
)
log = logging.getLogger("mcp-bridge")

# How long to wait for a response from the child process (seconds)
REQUEST_TIMEOUT = float(os.environ.get("MCP_BRIDGE_TIMEOUT", "30"))


class StdioBridge:
    """Manages a child process and proxies JSON-RPC over its stdio."""

    def __init__(self, command: str, args: list[str]):
        self.command = command
        self.args = args
        self.proc: asyncio.subprocess.Process | None = None
        # _pending is keyed by the internal id we send to the child; each entry
        # holds both the caller's original id and the Future awaiting the reply.
        # Keying by caller-supplied id would break as soon as two clients both
        # send the same id (e.g. every MCP client starts `initialize` at id=0)
        # because the second call would silently overwrite the first's future.
        self._pending: dict[str, tuple[str | int | None, asyncio.Future]] = {}
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task | None = None
        self._healthy = False

    async def start(self):
        log.info("Spawning: %s %s", self.command, " ".join(self.args))
        self.proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # MCP messages are newline-delimited JSON on stdout. asyncio's default
            # StreamReader limit is 64 KiB; a `tools/list` reply from a tool-rich
            # server (e.g. 100+ tools with input schemas) easily exceeds that,
            # which would overflow readline() and silently kill the reader — every
            # subsequent request then times out. Give it generous headroom.
            limit=16 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())
        self._healthy = True

    async def _read_stdout(self):
        """Read newline-delimited JSON-RPC messages from child stdout."""
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                log.warning("Child stdout closed")
                self._healthy = False
                # Fail all pending requests
                for _, fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("Child process exited"))
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                log.debug("Non-JSON stdout: %s", line[:200])
                continue
            internal_id = msg.get("id")
            if internal_id is not None and str(internal_id) in self._pending:
                original_id, future = self._pending[str(internal_id)]
                # Rewrite the id back to whatever the caller sent so the client
                # correlates it with its own request.
                msg["id"] = original_id
                if not future.done():
                    future.set_result(msg)
            else:
                # Notification from server (no id or unsolicited)
                log.debug("Notification: %s", msg.get("method", "unknown"))

    async def _read_stderr(self):
        """Log child stderr for debugging."""
        assert self.proc and self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                break
            log.info("Child stderr: %s", line.decode().rstrip())

    async def send(self, request: dict) -> dict:
        """Send a JSON-RPC request to the child and wait for the response.

        The request is rewritten with a bridge-scoped unique id before hitting
        the child, and the response's id is rewritten back before returning.
        This keeps concurrent clients from colliding on caller-supplied ids
        (e.g. every MCP session starts at id=0 for `initialize`).
        """
        assert self.proc and self.proc.stdin
        original_id = request.get("id")
        future: asyncio.Future | None = None
        internal_id: str | None = None
        outgoing = request

        if original_id is not None:
            internal_id = uuid.uuid4().hex
            future = asyncio.get_event_loop().create_future()
            self._pending[internal_id] = (original_id, future)
            outgoing = dict(request)
            outgoing["id"] = internal_id

        async with self._write_lock:
            data = json.dumps(outgoing) + "\n"
            self.proc.stdin.write(data.encode())
            await self.proc.stdin.drain()

        if future is not None and internal_id is not None:
            try:
                return await asyncio.wait_for(future, timeout=REQUEST_TIMEOUT)
            except asyncio.TimeoutError:
                log.error("Timeout waiting for response to request id=%s", original_id)
                return {
                    "jsonrpc": "2.0",
                    "id": original_id,
                    "error": {"code": -32000, "message": "Request timed out"},
                }
            finally:
                self._pending.pop(internal_id, None)

        # Notification (no id) — fire and forget
        return {}

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
        self._healthy = False


# ── HTTP Handlers ──────────────────────────────────────────────────────

# Process-scoped (not per-request): one bridge process wraps a single child
# stdio server, so all HTTP requests share the same logical MCP session.
SESSION_ID = str(uuid.uuid4())


async def handle_mcp_post(request: web.Request) -> web.Response:
    """Handle POST /mcp — streamable-http JSON-RPC endpoint."""
    bridge: StdioBridge = request.app["bridge"]

    if not bridge._healthy:
        return web.json_response(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "Child process not running"}},
            status=503,
        )

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status=400,
        )

    # Handle JSON-RPC batch
    if isinstance(body, list):
        responses = []
        for msg in body:
            resp = await bridge.send(msg)
            if resp:  # Skip empty (notification) responses
                responses.append(resp)
        return web.json_response(
            responses,
            headers={"Mcp-Session-Id": SESSION_ID},
        )

    response = await bridge.send(body)

    # For notifications (no id), return 202 Accepted
    if not response:
        return web.Response(
            status=202,
            headers={"Mcp-Session-Id": SESSION_ID},
        )

    return web.json_response(
        response,
        headers={"Mcp-Session-Id": SESSION_ID},
    )


async def handle_mcp_get(request: web.Request) -> web.Response:
    """Handle GET /mcp — SSE endpoint for server-initiated notifications.
    For now, returns an empty SSE stream (keep-alive). Most MCP servers
    don't send unsolicited notifications."""
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Mcp-Session-Id": SESSION_ID,
        },
    )
    await response.prepare(request)

    # Keep the connection open until client disconnects
    try:
        while True:
            await response.write(b": keepalive\n\n")
            await asyncio.sleep(30)
    except (ConnectionResetError, asyncio.CancelledError):
        pass

    return response


async def handle_mcp_delete(request: web.Request) -> web.Response:
    """Handle DELETE /mcp — close session."""
    return web.Response(status=200, headers={"Mcp-Session-Id": SESSION_ID})


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    bridge: StdioBridge = request.app["bridge"]
    if bridge._healthy:
        return web.json_response({"status": "healthy"})
    return web.json_response({"status": "unhealthy"}, status=503)


# ── Main ───────────────────────────────────────────────────────────────


async def main():
    if len(sys.argv) < 2:
        print("Usage: bridge.py <command> [args...]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]
    port = int(os.environ.get("PORT", "8080"))

    bridge = StdioBridge(command, args)
    await bridge.start()
    log.info("Bridge ready — serving streamable-http on port %d", port)

    app = web.Application()
    app["bridge"] = bridge

    # Streamable-http routes
    app.router.add_post("/mcp", handle_mcp_post)
    app.router.add_get("/mcp", handle_mcp_get)
    app.router.add_delete("/mcp", handle_mcp_delete)

    # Health (both /health and / for Go manager health checks)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    # Wait for child process to exit
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _on_signal():
        log.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)

    # Wait for either child exit or shutdown signal
    child_wait = asyncio.create_task(bridge.proc.wait())
    stop_wait = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        [child_wait, stop_wait],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if child_wait in done:
        log.warning("Child process exited with code %d", bridge.proc.returncode)

    await bridge.stop()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
