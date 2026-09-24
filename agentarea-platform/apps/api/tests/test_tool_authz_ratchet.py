"""Every tool states its authorization, the way every route does.

The platform toolsets served at ``/mcp`` call the same services as the REST
routers, and the worker binds toolsets from the code-tool registry into agent
runs. On 2026-09-24 only two of eighteen platform toolsets checked anything: a
member who could not delete a deny rule, invite a stranger, rotate a provider
key or read the audit log through the API could do all of it by asking an agent
to. ``test_authz_ratchet.py`` could not notice, because ``/mcp`` is a Starlette
mount and it enumerates ``APIRoute``s only.

Two surfaces are enumerated here, because they are not the same set: the
``/mcp`` toolsets (``get_platform_tools``) and every ``@toolset`` registered for
the worker. ``agentarea/triggers`` is the case that made the difference -- the
API's toolset is unregistered and the worker resolves the namespace to
``TriggersAgentToolset``, a second implementation with its own methods.

A tool declares, from ``agentarea_agents_sdk.tools.tool_authz``, one of
``requires``, ``requires_workspace_admin``, ``enforced_in_handler`` or
``unrestricted``, and this test fails on a tool that declares none. The two
enforcing markers are exercised for every tool that carries one: a caller
without the authority is refused before the body runs, and a caller with it
gets through.
"""

from __future__ import annotations

import inspect
import json
import sys
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_agents_sdk.tools.code_tools_loader import _ensure_all_toolsets_imported
from agentarea_agents_sdk.tools.tool_authz import tool_authz
from agentarea_agents_sdk.tools.tool_definition import get_toolset_registry
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


def _toolset_classes() -> list[type]:
    _ensure_all_toolsets_imported()
    classes = {type(toolset) for toolset in get_platform_tools()}
    classes |= set(get_toolset_registry().values())
    return sorted(classes, key=lambda cls: f"{cls.__module__}.{cls.__name__}")


TOOLS = [
    (cls, name, func)
    for cls in _toolset_classes()
    for name, func in inspect.getmembers(cls, predicate=inspect.isfunction)
    if getattr(func, "_is_tool_method", False)
]
GATED = [
    item for item in TOOLS if (tool_authz(item[2]) or {}).get("action") not in (None, "in-handler")
]


def _tool_id(item) -> str:
    cls, name, _func = item
    return f"{cls.__module__}.{cls.__name__}.{name}"


def test_both_surfaces_are_enumerated() -> None:
    """Guard against either source silently contributing nothing."""
    modules = {cls.__module__ for cls, _name, _func in TOOLS}
    assert "agentarea_triggers.agent_tool" in modules
    assert "agentarea_api.tools.triggers_toolset" in modules
    assert "agentarea_agents_sdk.tools.shell_toolset" in modules


def test_every_tool_declares_its_authorization() -> None:
    undeclared = sorted(_tool_id(item) for item in TOOLS if tool_authz(item[2]) is None)
    assert not undeclared, (
        "these tools declare no authorization:\n  "
        + "\n  ".join(undeclared)
        + "\n\nDecorate the tool with requires(...), requires_workspace_admin(), "
        "enforced_in_handler(reason) or unrestricted(reason) from "
        "agentarea_agents_sdk.tools.tool_authz, matching the REST route it mirrors."
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
def bound(monkeypatch):
    """A tool method whose body is observable: every toolset opens a context first."""

    @asynccontextmanager
    async def _entered():
        raise _BodyReachedError
        yield

    async def _open(*_args, **_kwargs):
        raise _BodyReachedError

    def bind(cls, name):
        module = sys.modules[cls.__module__]
        for attr in ("platform_context", "platform_read_context"):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, _entered)
        if hasattr(cls, "_open"):
            monkeypatch.setattr(cls, "_open", _open)
        return getattr(cls(), name)

    return bind


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
async def test_a_member_without_the_authority_is_refused(item, bound) -> None:
    cls, name, _func = item
    method = bound(cls, name)

    with use_mcp_user_context(MEMBER):
        result = json.loads(await method(**_arguments(method)))

    assert result.get("error") in REFUSALS


@pytest.mark.asyncio
@pytest.mark.parametrize("item", GATED, ids=_tool_id)
async def test_a_caller_with_the_authority_gets_through(item, bound) -> None:
    cls, name, _func = item
    method = bound(cls, name)

    with use_mcp_user_context(OWNER):
        try:
            result = await method(**_arguments(method))
        except _BodyReachedError:
            return

    assert json.loads(result).get("error") not in REFUSALS
