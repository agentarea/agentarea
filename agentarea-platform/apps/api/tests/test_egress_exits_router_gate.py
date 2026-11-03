"""The egress exits API exists only where the deployment enforces exits."""

import pytest
from agentarea_api.api.deps.services import get_egress_exit_service
from agentarea_api.api.v1 import egress_exits
from agentarea_common.extensions.egress_exits import EGRESS_EXITS_EXTENSION
from agentarea_common.extensions.registry import ExtensionRegistry
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Exits:
    async def list(self):
        return []


@pytest.fixture
def client():
    ExtensionRegistry.clear()
    app = FastAPI()
    app.include_router(egress_exits.router)
    app.dependency_overrides[get_egress_exit_service] = _Exits
    yield TestClient(app)
    ExtensionRegistry.clear()


def test_a_deployment_without_the_extension_has_no_egress_exits(client):
    response = client.get("/egress-exits/")

    assert response.status_code == 404
    assert "enterprise" in response.json()["detail"]


def test_the_extension_serves_them(client):
    ExtensionRegistry.register(EGRESS_EXITS_EXTENSION, lambda: True)

    response = client.get("/egress-exits/")

    assert response.status_code == 200
    assert response.json() == []
