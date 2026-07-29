from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.interfaces import ActivityDependencies
from pydantic import SecretStr


@pytest.mark.asyncio
async def test_cleanup_sandbox_task_uses_task_route() -> None:
    dependencies = ActivityDependencies(
        settings=MagicMock(),
        event_broker=AsyncMock(),
        secret_manager_factory=MagicMock(),
    )
    cleanup = next(
        item
        for item in make_agent_activities(dependencies)
        if item.__name__ == "cleanup_sandbox_task_activity"
    )
    response = MagicMock(status_code=204, text="")
    client = AsyncMock()
    client.delete.return_value = response
    client_context = AsyncMock()
    client_context.__aenter__.return_value = client

    settings = MagicMock(
        MCP_MANAGER_URL="http://mcp-manager",
        SANDBOX_CLEANUP_AUTH_SECRET=SecretStr("cleanup-secret-for-tests"),
    )
    with (
        patch("agentarea_common.config.mcp.MCPSettings", return_value=settings),
        patch("httpx.AsyncClient", return_value=client_context),
    ):
        await cleanup("task-123")

    client.delete.assert_awaited_once_with(
        "http://mcp-manager/sandbox/task/task-123",
        headers={"Authorization": "Bearer cleanup-secret-for-tests"},
    )


@pytest.mark.asyncio
async def test_cleanup_sandbox_task_fails_closed_without_secret() -> None:
    dependencies = ActivityDependencies(
        settings=MagicMock(),
        event_broker=AsyncMock(),
        secret_manager_factory=MagicMock(),
    )
    cleanup = next(
        item
        for item in make_agent_activities(dependencies)
        if item.__name__ == "cleanup_sandbox_task_activity"
    )
    client = AsyncMock()
    client_context = AsyncMock()
    client_context.__aenter__.return_value = client
    settings = MagicMock(
        MCP_MANAGER_URL="http://mcp-manager",
        SANDBOX_CLEANUP_AUTH_SECRET=None,
    )

    with (
        patch("agentarea_common.config.mcp.MCPSettings", return_value=settings),
        patch("httpx.AsyncClient", return_value=client_context),
    ):
        await cleanup("task-123")

    client.delete.assert_not_awaited()
