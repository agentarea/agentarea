"""Routes that answer 503 when a backing service is absent say so in the spec.

The live-stack fuzz tolerates a 503 from these operations only while the spec
documents it, so the documentation is load-bearing, not decoration.
"""

import pytest
from agentarea_api.api.v1 import mcp_server_instances, sandboxes
from fastapi import FastAPI


@pytest.mark.parametrize(
    ("router", "path", "method"),
    [
        (sandboxes.router, "/sandboxes", "get"),
        (mcp_server_instances.router, "/mcp-server-instances/check", "post"),
    ],
)
def test_the_unavailable_status_is_part_of_the_contract(router, path, method):
    app = FastAPI()
    app.include_router(router)

    responses = app.openapi()["paths"][path][method]["responses"]

    assert "503" in responses
