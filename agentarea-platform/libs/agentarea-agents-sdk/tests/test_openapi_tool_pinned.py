"""An OpenAPI tool call reaches only the address it vetted.

The base URL was validated once and then a fresh httpx client resolved the
name again, so a name that rebinds between the two reached an internal host.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

import agentarea_agents_sdk.tools.openapi_tool as mod


@pytest.mark.asyncio
async def test_a_base_url_that_passed_the_precheck_is_still_not_dialed_privately(monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.delenv("OUTBOUND_PRIVATE_ALLOWLIST", raising=False)
    connection = SimpleNamespace(
        id=uuid4(),
        name="api",
        base_url="http://127.0.0.1:1",
        spec_content=None,
        custom_headers=[],
        auth_config_id=None,
    )
    service = AsyncMock()
    service.get_connection = AsyncMock(return_value=connection)
    service.resolve_headers = AsyncMock(return_value={})
    service._allow_private_urls = False
    operation = {
        "name": "listItems",
        "description": "",
        "method": "GET",
        "path": "/items",
        "parameters": [],
        "request_body": None,
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }

    # Stands in for a name that resolved public when checked and private when dialed.
    with patch("agentarea_openapi.application.url_validator.validate_url", return_value=[]):
        tool = mod.OpenAPITool(operation, connection.id, "api", service)
        result = await tool.execute()

    assert result["success"] is False
    assert result["error"] == "Destination is not an allowed address"
