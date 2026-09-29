"""An installed api_router extension must actually reach the running app.

The extension point shipped working and inert: create_app() read the registry
at a point where nothing had populated it yet, because discovery ran from the
lifespan — i.e. after create_app() had already returned. get_factory returned
None, the mount block was skipped, and nothing was logged, so an installed,
working extension contributed no routes and raised no complaint. It took a
production 404 to notice.

A test that registers a factory by hand and then calls create_app() would have
passed against that bug: it skips the part that was broken. So these drive the
app the way a real deployment does — the routes have to arrive *through
discovery*.
"""

import agentarea_common.extensions as extensions_module
import pytest
from agentarea_api.main import create_app
from agentarea_common.extensions.registry import ExtensionRegistry
from fastapi import APIRouter

SENTINEL_PATH = "/v1/__extension_sentinel__"


def _sentinel_router() -> APIRouter:
    router = APIRouter()

    @router.get(SENTINEL_PATH)
    async def _sentinel() -> dict[str, bool]:
        return {"ok": True}

    return router


def _paths(app) -> set[str]:
    return {getattr(route, "path", None) for route in app.routes}


def test_routes_arrive_through_discovery(monkeypatch):
    """The registry must be populated by create_app itself, not by the caller."""
    ExtensionRegistry.clear()

    discovered = {"called": False}

    def fake_discover() -> None:
        # Stands in for an installed distribution advertising an entry point.
        discovered["called"] = True
        ExtensionRegistry.register("api_router", _sentinel_router)

    # main.py imports this name from the package inside create_app, so patching
    # the package attribute is what a real import would pick up.
    monkeypatch.setattr(extensions_module, "discover_extensions", fake_discover)

    try:
        app = create_app()
    finally:
        ExtensionRegistry.clear()

    assert discovered["called"], (
        "create_app never ran discovery, so an installed extension could only be "
        "mounted by luck — whoever happened to populate the registry first"
    )
    assert SENTINEL_PATH in _paths(app), (
        "the discovered extension contributed no routes to the app"
    )


def test_no_extension_is_not_an_error(monkeypatch):
    """Plain OSS — nothing installed — still builds a working app."""
    ExtensionRegistry.clear()
    monkeypatch.setattr(extensions_module, "discover_extensions", lambda: None)

    try:
        app = create_app()
    finally:
        ExtensionRegistry.clear()

    paths = _paths(app)
    assert SENTINEL_PATH not in paths
    assert "/health" in paths, "core routes must be served with no extension present"


def test_a_broken_extension_does_not_take_the_api_down(monkeypatch):
    """One unavailable feature must not become zero available features."""
    ExtensionRegistry.clear()

    def explode() -> APIRouter:
        raise RuntimeError("extension is broken")

    def fake_discover() -> None:
        ExtensionRegistry.register("api_router", explode)

    monkeypatch.setattr(extensions_module, "discover_extensions", fake_discover)

    try:
        app = create_app()
    finally:
        ExtensionRegistry.clear()

    assert "/health" in _paths(app)


def test_extension_cannot_shadow_a_core_route(monkeypatch):
    """Core routes are the contract; an extension is mounted after them."""
    ExtensionRegistry.clear()

    def shadowing_router() -> APIRouter:
        router = APIRouter()

        @router.get("/health")
        async def _hijacked() -> dict[str, str]:
            return {"status": "hijacked"}

        return router

    def fake_discover() -> None:
        ExtensionRegistry.register("api_router", shadowing_router)

    monkeypatch.setattr(extensions_module, "discover_extensions", fake_discover)

    try:
        app = create_app()
    finally:
        ExtensionRegistry.clear()

    health_routes = [r for r in app.routes if getattr(r, "path", None) == "/health"]
    assert len(health_routes) == 2, "expected the core route plus the extension's"
    # FastAPI matches in insertion order, so the core one must come first.
    core_index = min(i for i, r in enumerate(app.routes) if getattr(r, "path", None) == "/health")
    ext_index = max(i for i, r in enumerate(app.routes) if getattr(r, "path", None) == "/health")
    assert core_index < ext_index, "the extension was mounted ahead of the core route"


def _billing_router() -> APIRouter:
    from agentarea_common.auth.dependencies import UserContextDep

    router = APIRouter(prefix="/billing")

    @router.get("/overview")
    async def _overview(user: UserContextDep) -> dict[str, str]:
        return {"workspace_id": user.workspace_id}

    return router


def test_workspace_extension_routes_are_mounted_under_the_workspace(monkeypatch):
    """A route that acts in a workspace names it in the path, extension or not."""
    ExtensionRegistry.clear()

    def fake_discover() -> None:
        ExtensionRegistry.register("workspace_api_router", _billing_router)

    monkeypatch.setattr(extensions_module, "discover_extensions", fake_discover)

    try:
        app = create_app()
    finally:
        ExtensionRegistry.clear()

    assert "/v1/workspaces/{workspace}/billing/overview" in _paths(app)


def test_an_extension_route_that_names_no_workspace_refuses_to_build(monkeypatch):
    """Mounted at the root, a workspace-resolving route could only fail every request."""
    from agentarea_api.api.route_contract import RouteContractError

    ExtensionRegistry.clear()

    def fake_discover() -> None:
        ExtensionRegistry.register("api_router", _billing_router)

    monkeypatch.setattr(extensions_module, "discover_extensions", fake_discover)

    try:
        with pytest.raises(RouteContractError, match="/billing/overview"):
            create_app()
    finally:
        ExtensionRegistry.clear()
