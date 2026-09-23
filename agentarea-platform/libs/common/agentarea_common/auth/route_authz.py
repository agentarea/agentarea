"""Declarative authorization markers for API routes.

Authorization is declared on the route, not performed inside the handler. The
route is the only layer that has both the resolved path parameters (so it knows
*which* object is being touched) and the user context, while a middleware sees
only a path template. Domain invariants -- "the owner cannot be removed", "the
last member cannot leave" -- stay in the services; they are rules about the
object, not about the caller's authority.

Every write route must carry one of these markers. ``test_authz_ratchet.py``
enumerates the router and fails on any route that carries neither, so a new
endpoint cannot silently ship without an authorization decision.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request, params

from .authorization import assert_workspace_admin, assert_workspace_admin_of
from .dependencies import UserContextDep
from .permission import require_permission

AUTHZ_ATTR = "__route_authz__"


def requires(action: str, resource_type: str, *, id_param: str | None = None) -> params.Depends:
    """Demand ``action`` on ``resource_type`` before the handler runs.

    ``id_param`` names the path parameter holding the object's id. Omit it for
    workspace-wide actions, which resolve against the caller's workspace.
    """

    async def _check(request: Request, user_context: UserContextDep) -> None:
        resource_id = (
            str(request.path_params.get(id_param, ""))
            if id_param
            else str(user_context.workspace_id)
        )
        await require_permission(action, resource_type, resource_id, user_context.user_id)

    setattr(_check, AUTHZ_ATTR, {"action": action, "resource_type": resource_type})
    return Depends(_check)


def requires_workspace_admin(*, workspace_param: str | None = None) -> params.Depends:
    """Demand authority over the workspace itself, not just membership in it.

    For actions whose blast radius is everyone in the workspace: credentials,
    spend, access grants, the registries every agent installs from. This
    resolves through ``AuthorizationService.can_administer_workspace``, which
    answers from ownership even with no graph backend configured — unlike
    ``requires()``, whose open-core ``PermissionService`` allows everything
    until a graph is wired up.
    """

    async def _check(request: Request, user_context: UserContextDep) -> None:
        if workspace_param is None:
            await assert_workspace_admin(user_context)
            return
        # The workspace under administration is named in the path, which need
        # not be the one the caller is currently acting in.
        target = str(request.path_params.get(workspace_param, ""))
        await assert_workspace_admin_of(user_context, target)

    setattr(_check, AUTHZ_ATTR, {"action": "administer", "resource_type": "workspace"})
    return Depends(_check)


def enforced_in_handler(reason: str) -> params.Depends:
    """Declare that the handler itself decides, because the object decides it.

    Some authority questions cannot be answered before the object is loaded —
    "may this caller revoke *this* key", "is this agent in a project they
    manage". Those checks belong in the handler, but the route must still say
    that a decision happens, otherwise it is indistinguishable from a route
    where nobody thought about it.
    """
    if not reason.strip():
        raise ValueError("enforced_in_handler() requires a reason")

    async def _declared() -> None:
        return None

    setattr(
        _declared, AUTHZ_ATTR, {"action": "in-handler", "resource_type": None, "reason": reason}
    )
    return Depends(_declared)


def unrestricted(reason: str) -> params.Depends:
    """Declare that any authenticated member of the workspace may call this.

    This is a decision, not an omission, and ``reason`` records it at the call
    site. Use it for actions whose authority is enforced elsewhere (a domain
    service, a signed token) or that genuinely need no privilege.
    """
    if not reason.strip():
        raise ValueError("unrestricted() requires a reason")

    async def _noop() -> None:
        return None

    setattr(_noop, AUTHZ_ATTR, {"action": None, "resource_type": None, "reason": reason})
    return Depends(_noop)


def route_authz(route: Any) -> list[dict[str, Any]]:
    """Authorization markers declared on a route, for the ratchet test."""
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return []
    found: list[dict[str, Any]] = []
    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        marker = getattr(dep.call, AUTHZ_ATTR, None)
        if marker is not None:
            found.append(marker)
        stack.extend(dep.dependencies)
    return found
