"""Cancelling a run that already ended is refused, not reported as cancelled.

The route used to answer 200 ``{"status": "cancelled"}`` for a failed or blocked
task while the row kept its status, so the caller and the task disagreed.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import cancel_agent_task
from agentarea_common.auth.context import UserContext
from fastapi import HTTPException


@pytest.mark.parametrize("status", ["failed", "blocked", "cancelled"])
async def test_an_ended_task_is_not_cancelled_again(status):
    agent_id, task_id = uuid4(), uuid4()
    workflows = SimpleNamespace(cancel_task=AsyncMock(return_value=True))
    with pytest.raises(HTTPException) as raised:
        await cancel_agent_task(
            agent_id=agent_id,
            task_id=task_id,
            user_context=UserContext(user_id="u", workspace_id="w"),
            agent_service=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace())),
            task_service=SimpleNamespace(
                get_task=AsyncMock(
                    return_value=SimpleNamespace(id=task_id, agent_id=agent_id, status=status)
                )
            ),
            workflow_task_service=workflows,
        )
    assert raised.value.status_code == 409
    workflows.cancel_task.assert_not_awaited()
