"""Every route that acts in a workspace names that workspace in its URL.

The workspace moved from a request header into the path
(``/v1/workspaces/{workspace}/...``). Two things keep that true as routes are
added: the app refuses to build when a workspace-resolving route names no
workspace and binds none, and the generated SDK keeps its operation names
because the ``/workspaces/{workspace}`` segment is left out of them.
"""

import pytest
from agentarea_api.api.route_contract import RouteContractError, check_route_contract
from agentarea_api.main import create_app
from agentarea_common.auth.dependencies import (
    UserContextDep,
    bind_request_workspace,
    binds_workspace,
)
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.routing import APIRoute

WORKSPACE_PREFIX = "/v1/workspaces/{workspace}"


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="module")
def schema(app) -> dict:
    return app.openapi()


def _operation_ids(schema: dict) -> dict[tuple[str, str], str]:
    return {
        (method, path): operation["operationId"]
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and "operationId" in operation
    }


def test_a_workspace_route_outside_the_prefix_is_rejected():
    app = FastAPI()
    router = APIRouter(prefix="/v1")

    @router.get("/agents")
    async def list_agents(ctx: UserContextDep) -> list:
        return []

    app.include_router(router)

    with pytest.raises(RouteContractError, match="/v1/agents"):
        check_route_contract(app.routes)


def test_a_route_that_binds_its_entity_workspace_is_accepted():
    app = FastAPI()

    @binds_workspace
    async def bind(request: Request) -> None:
        bind_request_workspace(request, "ws", "ws")

    @app.get("/v1/agents/{agent_id}/a2a/rpc", dependencies=[Depends(bind)])
    async def rpc(agent_id: str, ctx: UserContextDep) -> dict:
        return {}

    check_route_contract(app.routes)


def test_a_binder_that_runs_after_the_workspace_context_is_rejected():
    """A binder resolved after get_user_context binds nothing in time for it."""
    app = FastAPI()

    @binds_workspace
    async def bind(request: Request) -> None:
        bind_request_workspace(request, "ws", "ws")

    @app.get("/v1/agents/{agent_id}/a2a/rpc")
    async def rpc(agent_id: str, ctx: UserContextDep, _bound: None = Depends(bind)) -> dict:
        return {}

    with pytest.raises(RouteContractError, match="/v1/agents/"):
        check_route_contract(app.routes)


def test_a_route_under_the_workspace_prefix_is_accepted():
    app = FastAPI()

    @app.get(f"{WORKSPACE_PREFIX}/agents")
    async def list_agents(ctx: UserContextDep) -> list:
        return []

    check_route_contract(app.routes)


def test_duplicate_operation_ids_are_rejected():
    app = FastAPI()

    @app.get("/v1/a", operation_id="same")
    async def a() -> dict:
        return {}

    @app.get("/v1/b", operation_id="same")
    async def b() -> dict:
        return {}

    with pytest.raises(RouteContractError, match="same"):
        check_route_contract(app.routes)


def test_the_real_app_satisfies_the_contract(app):
    check_route_contract(app.routes)


def test_workspace_routes_keep_the_operation_ids_they_had_without_the_segment(schema):
    operation_ids = _operation_ids(schema)

    assert operation_ids[("get", f"{WORKSPACE_PREFIX}/agents/")] == "list_agents_v1_agents__get"
    assert (
        operation_ids[("get", f"{WORKSPACE_PREFIX}/agents/{{agent_id}}")]
        == "get_agent_v1_agents__agent_id__get"
    )
    assert (
        operation_ids[
            ("get", f"{WORKSPACE_PREFIX}/agents/{{agent_id}}/tasks/{{task_id}}/events/stream")
        ]
        == "stream_task_events_v1_agents__agent_id__tasks__task_id__events_stream_get"
    )
    assert (
        operation_ids[("get", f"{WORKSPACE_PREFIX}/files")] == "list_workspace_files_v1_files_get"
    )
    assert operation_ids[("get", "/v1/workspaces")] == "list_workspaces_v1_workspaces_get"
    assert (
        operation_ids[("post", "/v1/agents/{agent_id}/a2a/rpc")]
        == "handle_agent_jsonrpc_v1_agents__agent_id__a2a_rpc_post"
    )


def test_every_workspace_scoped_route_declares_the_slug_pattern(schema):
    for path, item in schema["paths"].items():
        if not path.startswith(WORKSPACE_PREFIX):
            continue
        for operation in item.values():
            params = [p for p in operation.get("parameters", []) if p["name"] == "workspace"]
            assert params, f"{path} does not declare the workspace path parameter"
            assert params[0]["in"] == "path"
            assert params[0]["schema"].get("pattern"), f"{path} has no slug pattern"


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource",
        "/health",
        "/webhooks/{webhook_id}",
        "/v1/mcp-oauth/callback",
        "/v1/connections/oauth/callback",
        "/v1/agents/{agent_id}/.well-known/agent-card.json",
        "/v1/agents/{agent_id}/a2a/rpc",
        "/v1/agents/{agent_id}/a2a/well-known",
        "/v1/mcp/{instance_id}/mcp",
        "/v1/workspaces",
        "/v1/invitations/accept",
        "/v1/invitations/preview",
    ],
)
def test_unscoped_routes_keep_their_paths(app, path):
    assert path in {route.path for route in app.routes if isinstance(route, APIRoute)}


def test_workspace_headers_appear_nowhere_in_the_contract(schema):
    for item in schema["paths"].values():
        for operation in item.values():
            for param in operation.get("parameters", []):
                assert param["in"] != "header" or "workspace" not in param["name"].lower()
