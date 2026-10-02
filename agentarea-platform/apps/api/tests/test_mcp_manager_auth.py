from types import SimpleNamespace

import httpx
import pytest
from agentarea_api.api.v1 import mcp_server_instances
from agentarea_mcp.application import validation_service


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"valid": True, "errors": []}


class _Client:
    def __init__(self, requests):
        self._requests = requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, **kwargs):
        self._requests.append((url, kwargs))
        return _Response()


def _settings():
    return SimpleNamespace(
        mcp=SimpleNamespace(
            MCP_MANAGER_URL="http://manager",
            manager_inspection_headers=lambda: {"Authorization": "Bearer manager-test"},
        )
    )


@pytest.mark.asyncio
async def test_api_configuration_check_sends_manager_bearer(monkeypatch):
    requests = []
    monkeypatch.setattr(mcp_server_instances, "get_settings", _settings)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _Client(requests))

    result = await mcp_server_instances.check_mcp_server_instance_configuration(
        {"json_spec": {"type": "docker"}},
        SimpleNamespace(user_id="user", workspace_id="workspace"),
        None,
    )

    assert result["valid"] is True
    assert requests[0][0] == "http://manager/containers/validate"
    assert requests[0][1]["headers"]["Authorization"] == "Bearer manager-test"


@pytest.mark.asyncio
async def test_library_configuration_validation_sends_manager_bearer(monkeypatch):
    requests = []
    monkeypatch.setattr(validation_service, "get_settings", _settings)
    monkeypatch.setattr(
        validation_service.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _Client(requests),
    )

    errors = await validation_service.MCPConfigurationValidator.validate_with_golang_manager(
        {"type": "docker"}
    )

    assert errors == []
    assert requests[0][0].endswith("/containers/validate")
    assert requests[0][1]["headers"]["Authorization"] == "Bearer manager-test"
