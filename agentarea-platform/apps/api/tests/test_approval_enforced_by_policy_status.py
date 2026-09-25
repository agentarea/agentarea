"""Unticking a policy-enforced approval answers 409, not a 200 that changes nothing."""

import json
from unittest.mock import MagicMock

import pytest
from agentarea_agents.application.approval_sync import ApprovalEnforcedByPolicyError
from agentarea_api.main import app


@pytest.mark.asyncio
async def test_the_refusal_is_a_409_that_says_where_to_change_it():
    handler = app.exception_handlers[ApprovalEnforcedByPolicyError]

    response = await handler(MagicMock(), ApprovalEnforcedByPolicyError({"tool:files"}))

    assert response.status_code == 409
    body = json.loads(bytes(response.body))
    assert body["code"] == "approval_enforced_by_policy"
    assert "Policies page" in body["detail"]
    assert body["targets"] == ["tool:files"]
