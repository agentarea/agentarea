"""preview-spec must accept YAML specs whose unquoted values look like dates."""

import httpx
import pytest
from agentarea_api.api.v1 import openapi_connections
from agentarea_api.api.v1.openapi_connections import SpecPreviewRequest, preview_spec
from agentarea_openapi.application import service as openapi_service

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
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, text=BARE_DATE_YAML_SPEC))
    monkeypatch.setattr(
        openapi_service.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
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
