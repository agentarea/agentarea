"""Regression tests for stable, unique public OpenAPI operation IDs."""

from collections import defaultdict

from agentarea_api.api.v1 import webhooks
from agentarea_api.api.v1.mcp_oauth_as import oauth_as_router
from agentarea_api.api.v1.router import protected_v1_router, public_v1_router
from fastapi import FastAPI
from fastapi.routing import APIRoute


def _application() -> FastAPI:
    app = FastAPI()
    app.include_router(oauth_as_router)
    app.include_router(webhooks.router)
    app.include_router(public_v1_router)
    app.include_router(protected_v1_router)
    return app


def _application_schema() -> dict:
    return _application().openapi()


def test_main_router_has_no_duplicate_method_path_identities() -> None:
    routes_by_identity: dict[tuple[str, str], list[str]] = defaultdict(list)

    for route in _application().routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            routes_by_identity[(method, route.path)].append(route.name)

    duplicates = {
        identity: route_names
        for identity, route_names in routes_by_identity.items()
        if len(route_names) > 1
    }
    assert duplicates == {}


def test_openapi_operation_ids_are_unique() -> None:
    operations_by_id: dict[str, list[str]] = defaultdict(list)

    for path, path_item in _application_schema()["paths"].items():
        for method, operation in path_item.items():
            if isinstance(operation, dict) and "operationId" in operation:
                operations_by_id[operation["operationId"]].append(f"{method.upper()} {path}")

    duplicates = {
        operation_id: operations
        for operation_id, operations in operations_by_id.items()
        if len(operations) > 1
    }
    assert duplicates == {}


def test_multi_method_proxy_operation_ids_remain_stable() -> None:
    schema = _application_schema()
    expected = {
        "/oauth2/{path}": {
            "get": "hydra_oauth2_proxy_oauth2__path__get",
            "post": "hydra_oauth2_proxy_oauth2__path__post",
            "put": "hydra_oauth2_proxy_oauth2__path__put",
            "patch": "hydra_oauth2_proxy_oauth2__path__patch",
            "delete": "hydra_oauth2_proxy_oauth2__path__delete",
        },
        "/webhooks/{webhook_id}": {
            "get": "handle_webhook_webhooks__webhook_id__get",
            "post": "handle_webhook_webhooks__webhook_id__post",
            "put": "handle_webhook_webhooks__webhook_id__put",
            "patch": "handle_webhook_webhooks__webhook_id__patch",
            "delete": "handle_webhook_webhooks__webhook_id__delete",
            "head": "handle_webhook_webhooks__webhook_id__head",
            "options": "handle_webhook_webhooks__webhook_id__options",
        },
        "/v1/mcp/{instance_id}/mcp": {
            "get": "proxy_instance_v1_mcp__instance_id__mcp_get",
            "post": "proxy_instance_v1_mcp__instance_id__mcp_post",
            "delete": "proxy_instance_v1_mcp__instance_id__mcp_delete",
        },
    }

    actual = {
        path: {method: schema["paths"][path][method]["operationId"] for method in operation_ids}
        for path, operation_ids in expected.items()
    }
    assert actual == expected
