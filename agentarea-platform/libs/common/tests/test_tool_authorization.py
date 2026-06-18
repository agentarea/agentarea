"""Tests for the single tool invocation authorization PDP."""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationRequest,
    authorize_tool_invocation,
    decide_tool_policy,
)
from agentarea_common.config import get_settings
from agentarea_common.rebac.models import CheckResult


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch):
    monkeypatch.delenv("ACCESS_CONTROL_BACKEND", raising=False)
    monkeypatch.setenv("WORKFLOW__TEMPORAL_SERVER_URL", "localhost:7233")
    monkeypatch.setenv("WORKFLOW__TEMPORAL_NAMESPACE", "default")
    monkeypatch.setenv("WORKFLOW__TEMPORAL_TASK_QUEUE", "test-task-queue")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_policy_denies_when_allowlist_missing():
    assert decide_tool_policy(None, "web_search").action is ToolAuthorizationAction.DENY
    assert decide_tool_policy({}, "web_search").action is ToolAuthorizationAction.DENY


def test_policy_deny_beats_allow_all_and_approval():
    policy = {
        "tools": {"allowed": ["*"], "denied": ["shell_exec"]},
        "approval": {"requires_human_approval": True},
    }

    decision = decide_tool_policy(policy, "shell_exec")

    assert decision.action is ToolAuthorizationAction.DENY


def test_policy_requires_approval_only_after_explicit_allow():
    policy = {
        "tools": {"allowed": ["shell_exec"]},
        "approval": {"escalation_rules": ["shell_exec"]},
    }

    decision = decide_tool_policy(policy, "shell_exec")

    assert decision.action is ToolAuthorizationAction.REQUIRE_APPROVAL


@pytest.mark.asyncio
async def test_task_policy_allow_all_bypasses_graph(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "disabled")
    get_settings.cache_clear()
    openfga = AsyncMock()

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="web_search",
            tool_args={"query": "x"},
            user_id="u1",
            workspace_id="ws-1",
            effective_policy={"tools": {"allowed": ["*"]}},
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.ALLOW
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_scoped_task_policy_denies_when_graph_disabled(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "disabled")
    get_settings.cache_clear()

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="web_search",
            tool_args={"query": "x"},
            user_id="u1",
            workspace_id="ws-1",
            effective_policy={"tools": {"allowed": ["web_*"]}},
        )
    )

    assert decision.action is ToolAuthorizationAction.DENY
    assert decision.reason == "OpenFGA tool authorization is disabled"


@pytest.mark.asyncio
async def test_scoped_task_policy_allows_when_graph_allows(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()
    openfga.check.return_value = CheckResult(allowed=True)

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="web_search",
            tool_args={"query": "x"},
            user_id="u1",
            workspace_id="ws-1",
            effective_policy={"tools": {"allowed": ["web_*"]}},
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.ALLOW
    openfga.check.assert_awaited_once()


@pytest.mark.asyncio
async def test_scoped_task_policy_denies_when_graph_denies(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()
    openfga.check.return_value = CheckResult(allowed=False)

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="web_search",
            tool_args={"query": "x"},
            user_id="u1",
            workspace_id="ws-1",
            effective_policy={"tools": {"allowed": ["web_*"]}},
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.DENY
    assert decision.reason == "OpenFGA denied this tool invocation"


@pytest.mark.asyncio
async def test_scoped_task_policy_requires_user_id(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="web_search",
            tool_args={"query": "x"},
            effective_policy={"tools": {"allowed": ["web_*"]}},
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.DENY
    assert decision.reason == "missing user_id for tool authorization"
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_scoped_task_policy_requires_workspace_id(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="web_search",
            tool_args={"query": "x"},
            user_id="u1",
            effective_policy={"tools": {"allowed": ["web_*"]}},
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.DENY
    assert decision.reason == "missing workspace_id for tool authorization"
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_proxy_graph_only_mode_does_not_require_task_policy(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()
    openfga.check.return_value = CheckResult(allowed=True)

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="github.create_issue",
            tool_args={"repo": "acme/app"},
            user_id="u1",
            workspace_id="ws-1",
            policy_required=False,
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.ALLOW
    openfga.check.assert_awaited_once()
