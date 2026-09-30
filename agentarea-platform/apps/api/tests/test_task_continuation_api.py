from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import ContinueTaskPayload, continue_task_execution
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_continue_endpoint_accepts_waiting_task(test_user_context):
    task_id = uuid4()
    task_service = AsyncMock()
    task_service.continue_execution.return_value = {
        "accepted": True,
        "continuation_count": 1,
    }

    result = await continue_task_execution(
        task_id=task_id,
        payload=ContinueTaskPayload(
            additional_iterations=3,
            additional_budget_usd="2.50",
        ),
        user_context=test_user_context,
        task_service=task_service,
    )

    assert result["accepted"] is True
    task_service.continue_execution.assert_awaited_once()
    call = task_service.continue_execution.await_args
    assert call.args == (task_id,)
    assert call.kwargs["additional_iterations"] == 3
    assert str(call.kwargs["additional_budget_usd"]) == "2.50"
    assert call.kwargs["additional_tokens"] == 0
    assert call.kwargs["additional_tool_calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grant",
    [{"additional_tokens": 50_000}, {"additional_tool_calls": 25}],
)
async def test_continue_endpoint_accepts_token_or_tool_call_grant_alone(
    test_user_context, grant
):
    task_id = uuid4()
    task_service = AsyncMock()
    task_service.continue_execution.return_value = {"accepted": True}

    await continue_task_execution(
        task_id=task_id,
        payload=ContinueTaskPayload(**grant),
        user_context=test_user_context,
        task_service=task_service,
    )

    call = task_service.continue_execution.await_args
    assert call.kwargs["additional_tokens"] == grant.get("additional_tokens", 0)
    assert call.kwargs["additional_tool_calls"] == grant.get("additional_tool_calls", 0)
    assert call.kwargs["additional_iterations"] == 0
    assert call.kwargs["additional_budget_usd"] is None


@pytest.mark.parametrize(
    "grant",
    [
        {"additional_tokens": -1},
        {"additional_tokens": 10_000_001},
        {"additional_tool_calls": -1},
        {"additional_tool_calls": 10_001},
    ],
)
def test_continue_payload_bounds_token_and_tool_call_grants(grant):
    with pytest.raises(ValidationError):
        ContinueTaskPayload(**grant)


@pytest.mark.asyncio
async def test_continue_endpoint_returns_409_unless_waiting(test_user_context):
    task_service = AsyncMock()
    task_service.continue_execution.return_value = {
        "accepted": False,
        "reason": "not_waiting_for_continuation",
    }

    with pytest.raises(HTTPException) as exc_info:
        await continue_task_execution(
            task_id=uuid4(),
            payload=ContinueTaskPayload(additional_iterations=3),
            user_context=test_user_context,
            task_service=task_service,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reason"] == "not_waiting_for_continuation"


@pytest.mark.asyncio
async def test_continue_endpoint_requires_a_resource_grant(test_user_context):
    task_service = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await continue_task_execution(
            task_id=uuid4(),
            payload=ContinueTaskPayload(),
            user_context=test_user_context,
            task_service=task_service,
        )

    assert exc_info.value.status_code == 422
    task_service.continue_execution.assert_not_awaited()
