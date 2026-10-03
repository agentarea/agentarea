from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.v1 import mcp_server_instances
from agentarea_mcp.package_import import (
    MCPRuntimeRetirementConflictError,
    MCPRuntimeRetirementError,
)
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_delete_maps_runtime_retirement_conflict_to_retryable_409():
    instance_id = uuid4()

    class Service:
        async def delete_instance(self, _instance_id: UUID):
            raise MCPRuntimeRetirementConflictError("MCP runtime is still retiring this instance")

    with pytest.raises(HTTPException) as exc_info:
        await mcp_server_instances.delete_mcp_server_instance(
            instance_id, cast(Any, None), cast(Any, Service())
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.headers == {"Retry-After": "1"}
    assert "still retiring" in exc_info.value.detail


@pytest.mark.asyncio
async def test_delete_maps_runtime_retirement_failure_to_service_unavailable():
    instance_id = uuid4()

    class Service:
        async def delete_instance(self, _instance_id: UUID):
            raise MCPRuntimeRetirementError("MCP runtime retirement is temporarily unavailable")

    with pytest.raises(HTTPException) as exc_info:
        await mcp_server_instances.delete_mcp_server_instance(
            instance_id, cast(Any, None), cast(Any, Service())
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "1"}
    assert "temporarily unavailable" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_maps_runtime_retirement_conflict_to_retryable_409():
    instance_id = uuid4()

    class Service:
        async def update_instance(self, _instance_id: UUID, _data: Any):
            raise MCPRuntimeRetirementConflictError("MCP runtime is still retiring this instance")

    with pytest.raises(HTTPException) as exc_info:
        await mcp_server_instances.update_mcp_server_instance(
            instance_id, cast(Any, None), cast(Any, None), cast(Any, Service())
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.headers == {"Retry-After": "1"}
    assert "still retiring" in exc_info.value.detail
