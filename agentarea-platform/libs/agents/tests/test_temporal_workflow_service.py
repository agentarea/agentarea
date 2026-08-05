"""Failure handling for Temporal workflow status queries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService


@pytest.mark.asyncio
async def test_workflow_status_failure_hides_upstream_exception_details() -> None:
    execution_service = SimpleNamespace(
        get_status=AsyncMock(
            side_effect=RuntimeError("temporal endpoint failed: token=private-value")
        )
    )
    service = TemporalWorkflowService(execution_service)

    status = await service.get_workflow_status("workflow-1")

    assert status == {
        "status": "error",
        "success": False,
        "error": "Workflow status unavailable",
    }
