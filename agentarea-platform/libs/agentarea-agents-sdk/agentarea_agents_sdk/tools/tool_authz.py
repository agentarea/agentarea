"""Authorization declarations for toolsets.

A platform toolset calls the same services as the REST router beside it, so a
tool must answer the same authorization question as the route it mirrors. Until
2026-09-24 only the routes did: ``/mcp`` is a Starlette mount the route ratchet
cannot see, the worker binds the same toolsets into agent runs, and every check
that lived on a router was simply absent on both.

Every ``@tool_method`` of every ``@toolset`` now carries one of these, the tool
counterpart of ``agentarea_common.auth.route_authz``:

- ``requires(action, resource_type, id_param=...)`` -- the PDP decides before
  the body runs,
- ``requires_workspace_admin()`` -- authority over the workspace itself,
- ``enforced_in_handler(reason)`` -- the body, or the service it calls, decides,
- ``unrestricted(reason)`` -- any authenticated member may call it.

``apps/api/tests/test_tool_authz_ratchet.py`` fails on a tool that declares
none. The two enforcing markers wrap the method, so the declaration and the
check cannot drift apart; a refusal is returned as the tool's JSON error, the
shape every tool body already uses. They answer for the principal bound by
``use_mcp_user_context`` -- the MCP bearer, or the run's user in the worker.

The platform imports stay inside the checks, as in ``mcp_server.auth``: the
declarations are needed wherever a toolset is defined, the checks only where
one runs against the platform.
"""

from __future__ import annotations

import functools
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

TOOL_AUTHZ_ATTR = "__tool_authz__"

_Check = Callable[[dict[str, Any], Any], Awaitable[None]]


def _declare(func: Any, marker: dict[str, Any]) -> Any:
    setattr(func, TOOL_AUTHZ_ATTR, marker)
    return func


def _enforcing(marker: dict[str, Any], check: _Check) -> Callable[[Any], Any]:
    def decorate(func: Any) -> Any:
        signature = inspect.signature(func)

        @functools.wraps(func)
        async def guarded(*args: Any, **kwargs: Any) -> Any:
            from fastapi import HTTPException

            from ..mcp_server.auth import get_mcp_user_context

            arguments = signature.bind(*args, **kwargs).arguments
            try:
                await check(arguments, get_mcp_user_context())
            except HTTPException as exc:
                return json.dumps({"error": exc.detail})
            return await func(*args, **kwargs)

        return _declare(guarded, marker)

    return decorate


def requires(
    action: str, resource_type: str, *, id_param: str | None = None
) -> Callable[[Any], Any]:
    """Demand ``action`` on ``resource_type`` before the tool body runs.

    ``id_param`` names the argument holding the object's id; omit it for a
    workspace-wide action, which resolves against the caller's workspace.
    """

    async def check(arguments: dict[str, Any], user_context: Any) -> None:
        from agentarea_common.auth.permission import require_permission

        resource_id = str(arguments[id_param]) if id_param else str(user_context.workspace_id)
        await require_permission(action, resource_type, resource_id, user_context.user_id)

    return _enforcing({"action": action, "resource_type": resource_type}, check)


def requires_workspace_admin() -> Callable[[Any], Any]:
    """Demand authority over the caller's workspace, not just membership in it."""

    async def check(_arguments: dict[str, Any], user_context: Any) -> None:
        from agentarea_common.auth.authorization import assert_workspace_admin

        await assert_workspace_admin(user_context)

    return _enforcing({"action": "administer", "resource_type": "workspace"}, check)


def enforced_in_handler(reason: str) -> Callable[[Any], Any]:
    """Declare that the body, or the service it calls, makes the decision.

    For checks that need the object loaded first, and for authority that lives
    in the service so every caller surface inherits it. ``reason`` names where.
    """
    if not reason.strip():
        raise ValueError("enforced_in_handler() requires a reason")
    marker = {"action": "in-handler", "resource_type": None, "reason": reason}
    return lambda func: _declare(func, marker)


def unrestricted(reason: str) -> Callable[[Any], Any]:
    """Declare that any authenticated member of the workspace may call this tool."""
    if not reason.strip():
        raise ValueError("unrestricted() requires a reason")
    marker = {"action": None, "resource_type": None, "reason": reason}
    return lambda func: _declare(func, marker)


def tool_authz(method: Any) -> dict[str, Any] | None:
    """The authorization a tool method declares, for the ratchet test."""
    return getattr(method, TOOL_AUTHZ_ATTR, None)
