"""Every platform tool states its authorization, the way every route does.

The platform toolsets served at ``/mcp`` -- and bound into agent runs by the
worker's code-tool activity -- call the same services as the REST routers. On
2026-09-24 only two of eighteen toolsets checked anything: a member who could
not delete a deny rule, invite a stranger, rotate a provider key or read the
audit log through the API could do all of it by asking an agent to.
``test_authz_ratchet.py`` could not notice, because ``/mcp`` is a Starlette
mount and it enumerates ``APIRoute``s only.

So a tool declares, from ``agentarea_agents.tools.platform_authz``, one of
``requires``, ``requires_workspace_admin``, ``enforced_in_handler`` or
``unrestricted``, and this test fails on a tool that declares none.

The two enforcing markers are exercised for every tool that carries one: a
caller without the authority is refused before the body runs, and a caller
with it gets through.
"""

from __future__ import annotations

import inspect
import json
import sys
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from agentarea_agents.tools.platform_authz import tool_authz
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.tools import get_platform_tools
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import PermissionService
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container

WORKSPACE = "ws-acme"
MEMBER = UserContext(user_id="user-member", workspace_id=WORKSPACE, admin_workspaces=[])
OWNER = UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
REFUSALS = {"Permission denied", "Only a workspace admin may perform this action"}

TOOLS = [
    (toolset, name, method)
    for toolset in get_platform_tools()
    for name, method in toolset._tool_methods.items()
]
GATED = [
    (toolset, name, method)
    for toolset, name, method in TOOLS
    if (tool_authz(method) or {}).get("action") not in (None, "in-handler")
]


def _tool_id(item) -> str:
    toolset, name, _method = item
    return f"{toolset.name}_{name}"


def test_every_platform_tool_declares_its_authorization() -> None:
    undeclared = sorted(_tool_id(item) for item in TOOLS if tool_authz(item[2]) is None)
    assert not undeclared, (
        "these platform tools declare no authorization:\n  "
        + "\n  ".join(undeclared)
        + "\n\nDecorate the tool with requires(...), requires_workspace_admin(), "
        "enforced_in_handler(reason) or unrestricted(reason) from "
        "agentarea_agents.tools.platform_authz, matching the REST route it mirrors."
    )


def test_a_reason_is_required_where_no_check_runs() -> None:
    for item in TOOLS:
        marker = tool_authz(item[2]) or {}
        if marker.get("action") in (None, "in-handler"):
            reason = (marker.get("reason") or "").strip()
            assert len(reason) > 20, f"{_tool_id(item)}: declares no real reason ({reason!r})"


def test_the_enforcing_markers_are_actually_in_use() -> None:
    """Guard against the parametrized tests below silently collecting nothing."""
    assert len(GATED) > 10


class _BodyReachedError(Exception):
    pass


class _OwnerOnlyPermissions(PermissionService):
    async def check(self, user_id, permission, resource_type, resource_id) -> bool:
        return user_id == OWNER.user_id


@pytest.fixture(autouse=True)
def _authorization():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    container.register_singleton(PermissionService, _OwnerOnlyPermissions())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


@pytest.fixture
def body_guard(monkeypatch):
    """Make entering any tool body observable: every toolset opens a platform context."""

    @asynccontextmanager
    async def _entered():
        raise _BodyReachedError
        yield

    def install(method) -> None:
        module = sys.modules[inspect.unwrap(method).__module__]
        for name in ("platform_context", "platform_read_context"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, _entered)

    return install


def _arguments(method) -> dict:
    values = {bool: False, int: 1, dict: {}, list: []}
    arguments = {}
    for name, param in inspect.signature(method).parameters.items():
        if param.default is not inspect.Parameter.empty:
            continue
        annotation = param.annotation
        if isinstance(annotation, str):
            annotation = {"bool": bool, "int": int}.get(annotation, annotation)
        arguments[name] = values.get(annotation, str(uuid4()))
    return arguments


@pytest.mark.asyncio
@pytest.mark.parametrize("item", GATED, ids=_tool_id)
async def test_a_member_without_the_authority_is_refused(item, body_guard) -> None:
    _toolset, _name, method = item
    body_guard(method)

    with use_mcp_user_context(MEMBER):
        result = json.loads(await method(**_arguments(method)))

    assert result.get("error") in REFUSALS


@pytest.mark.asyncio
@pytest.mark.parametrize("item", GATED, ids=_tool_id)
async def test_a_caller_with_the_authority_gets_through(item, body_guard) -> None:
    _toolset, _name, method = item
    body_guard(method)

    with use_mcp_user_context(OWNER):
        try:
            result = await method(**_arguments(method))
        except _BodyReachedError:
            return

    assert json.loads(result).get("error") not in REFUSALS
