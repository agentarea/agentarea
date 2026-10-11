"""preview-spec accepts YAML specs whose unquoted values look like dates, and
answers a malformed spec with 400, as creating a connection from one does."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from agentarea_api.api.v1 import openapi_connections
from agentarea_api.api.v1.openapi_connections import (
    SpecPreviewRequest,
    create_connection,
    preview_spec,
)
from agentarea_common.utils.url_safety import OutboundPolicy
from agentarea_openapi.application import service as openapi_service
from agentarea_openapi.application.service import OpenAPIConnectionService
from agentarea_openapi.schemas.dto import OpenAPIConnectionCreate
from fastapi import HTTPException

BARE_DATE_YAML_SPEC = """\
openapi: 3.0.0
info:
  title: Dated API
  version: 2024-01-01
paths:
  /users:
    get:
      operationId: listUsers
      summary: List users
"""


@pytest.mark.asyncio
async def test_preview_yaml_spec_with_bare_date_version(monkeypatch):
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, text=BARE_DATE_YAML_SPEC))
    monkeypatch.setattr(
        openapi_service,
        "safe_async_client",
        lambda *, policy, **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        openapi_connections.OutboundPolicy,
        "from_env",
        classmethod(lambda cls: cls(allow_private=True)),
    )

    preview = await preview_spec(
        SpecPreviewRequest.model_construct(spec_url="http://127.0.0.1/openapi.yaml"),
        _service=None,  # type: ignore[arg-type]
    )

    assert preview.version == "2024-01-01"
    assert [t["name"] for t in preview.tools] == ["listUsers"]


MALFORMED_SPECS = [
    {"openapi": "3.0.0", "paths": {"/a": {"get": "x"}}},
    {"openapi": "3.0.0", "info": "str", "paths": {}},
    {"openapi": "3.0.0", "servers": ["x"], "paths": {}},
    {"openapi": "3.0.0", "servers": "notalist", "paths": {}},
    {"openapi": "3.0.0", "paths": {"/a": {"get": {"parameters": "x"}}}},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", MALFORMED_SPECS)
async def test_preview_of_a_malformed_spec_is_a_400(spec):
    """``.get`` on a string raised AttributeError, which the route let through as a 500."""
    with pytest.raises(HTTPException) as raised:
        await preview_spec(
            SpecPreviewRequest(spec_content=spec),
            _service=None,  # type: ignore[arg-type]
        )

    assert raised.value.status_code == 400
    assert "Invalid OpenAPI spec" in raised.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", MALFORMED_SPECS)
async def test_creating_a_connection_from_a_malformed_spec_is_a_400(spec, monkeypatch):
    monkeypatch.setattr(openapi_service, "validate_url", lambda *_args, **_kwargs: [])
    factory = MagicMock()
    factory.create_repository.return_value = AsyncMock()
    service = OpenAPIConnectionService(
        repository_factory=factory,
        secret_manager=AsyncMock(),
        auth_config_access_checker=AsyncMock(),
        outbound_policy=OutboundPolicy(),
    )

    with pytest.raises(HTTPException) as raised:
        await create_connection(
            OpenAPIConnectionCreate.model_construct(
                name="x", base_url="https://api.example.com", spec_content=spec
            ),
            service=service,
        )

    assert raised.value.status_code == 400
    assert "Invalid OpenAPI spec" in raised.value.detail
    service._repo.create.assert_not_awaited()
