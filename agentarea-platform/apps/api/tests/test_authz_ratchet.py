"""Every route states its authorization. There are no undeclared ones left.

An audit on 2026-09-22 found 149 write endpoints of which 19 performed any
authority check, and those 19 did it three different ways -- an in-body
``_assert_workspace_admin``, a membership-only ``_ensure_workspace_access``, or
a check buried in a domain service. Nothing failed when a route had none, so
secrets, provider API keys, MCP credentials and workspace spend caps were all
mutable by any member.

Reads were covered a day later, for the same reason in the other direction:
"any member may read anything the workspace holds" is a decision somebody has
to make per endpoint, not a default that falls out of nobody looking. It turned
up live OAuth link tokens, the audit log and the usage ledger, all readable by
every member.

A route now declares one of four things, from
``agentarea_common.auth.route_authz``:

- ``requires(action, resource_type)`` -- the PDP decides,
- ``requires_workspace_admin()`` -- authority over the workspace itself,
- ``enforced_in_handler(reason)`` -- the object must be loaded before the
  question can be answered, so the handler decides and says so,
- ``unrestricted(reason)`` -- any authenticated member may call it, and the
  reason records why that is the right answer.

The distinction that matters is not allow versus deny; it is *decided* versus
*never considered*. This test fails on the latter.
"""

from __future__ import annotations

from agentarea_api.main import app
from agentarea_common.auth.route_authz import route_authz
from fastapi.routing import APIRoute

HTTP_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}

# Routes that belong to the framework or to a mount, not to this application.
_NOT_OURS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _all_routes() -> list[APIRoute]:
    """Every route the running app serves.

    Enumerated from ``app.routes`` rather than from the two ``/v1`` routers,
    because the app mounts more than those two: the RFC 9728 OAuth metadata
    router, the webhook receiver (deliberately outside ``/v1`` to bypass the
    auth middleware), and whatever an installed extension contributes. The
    extension router is the reason this matters most -- it is assembled outside
    this repository, so a fence drawn around our own routers would not see it
    at all.
    """
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path not in _NOT_OURS
    ]


def _undeclared() -> set[str]:
    found: set[str] = set()
    for route in _all_routes():
        if route_authz(route):
            continue
        found |= {f"{m} {route.path}" for m in route.methods & HTTP_METHODS}
    return found


def test_every_route_declares_its_authorization() -> None:
    undeclared = _undeclared()
    assert not undeclared, (
        "these routes declare no authorization:\n  "
        + "\n  ".join(sorted(undeclared))
        + "\n\nAdd requires(...), requires_workspace_admin(), enforced_in_handler(reason) "
        "or unrestricted(reason) to the route's dependencies. There is no debt list to "
        "append to: an endpoint nobody decided about is the bug this test exists for."
    )


def test_a_reason_is_required_where_no_check_runs() -> None:
    """``unrestricted`` and ``enforced_in_handler`` must say why, not just that."""
    for route in _all_routes():
        if not route.methods & HTTP_METHODS:
            continue
        for marker in route_authz(route):
            if marker.get("action") in (None, "in-handler"):
                reason = (marker.get("reason") or "").strip()
                assert len(reason) > 20, (
                    f"{sorted(route.methods & HTTP_METHODS)} {route.path}: "
                    f"declares no real reason ({reason!r})"
                )
