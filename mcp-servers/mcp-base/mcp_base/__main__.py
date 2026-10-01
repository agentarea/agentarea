"""mcp-base entrypoint: ``python -m mcp_base <command> [args...]``.

Runs a stdio MCP server command behind the bridge on ``$PORT`` (8080). The
port opens once the server has initialized; the process exits non-zero when it
does not initialize within ``MCP_BASE_STARTUP_TIMEOUT`` seconds (300) or when
it stops running.

An image built ``FROM`` this one sets its server command as ``CMD``; an MCP
server that speaks Streamable HTTP itself sets its own ``ENTRYPOINT``
instead and does not need the bridge.
"""


from __future__ import annotations
from builtins import BaseExceptionGroup

import functools
import logging
import os
import sys

import anyio
from mcp import MCPError

from . import pack, stdio_bridge

# Settings of the bridge itself. The child must not see PORT in particular:
# some servers switch to serving HTTP on it, which would collide with ours.
BRIDGE_ENV = ("PORT", "MCP_BASE_STARTUP_TIMEOUT")


def _first_leaf(group: BaseExceptionGroup) -> BaseException:
    leaf: BaseException = group
    while isinstance(leaf, BaseExceptionGroup):
        leaf = leaf.exceptions[0]
    return leaf


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[mcp-base] %(message)s")
    if "MCP_BASE_PACK_ECOSYSTEM" in os.environ:
        pack.main()
        return
    command = sys.argv[1:]
    if not command:
        sys.exit(__doc__)
    try:
        anyio.run(
            functools.partial(
                stdio_bridge.serve,
                command,
                cwd=None,
                env={k: v for k, v in os.environ.items() if k not in BRIDGE_ENV},
                port=int(os.environ.get("PORT", "8080")),
                startup_timeout_seconds=float(os.environ.get("MCP_BASE_STARTUP_TIMEOUT", "300")),
            )
        )
    except* (stdio_bridge.StartupTimeoutError, stdio_bridge.ChildExitedError) as failure:
        sys.exit(f"[mcp-base] {_first_leaf(failure)}")
    except* MCPError as failure:
        # Only initialization can surface a protocol error here: after it, the
        # SDK answers each forwarded request's error to its caller.
        sys.exit(
            f"[mcp-base] the stdio server stopped before it initialized ({_first_leaf(failure)}); "
            "its output is above"
        )


if __name__ == "__main__":
    main()
