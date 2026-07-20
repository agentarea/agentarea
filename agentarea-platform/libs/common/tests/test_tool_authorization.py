"""Tests for the single tool invocation authorization PDP.

Task paths are policy-only: the resolved snapshot (composition + policy) is
authoritative, and the OpenFGA graph is not consulted — so disclosure, the
workflow gate, and the activity read one answer. The graph remains the control
surface only for the policy-less MCP proxy path (``policy_required=False``),
which has no snapshot.
"""

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


# --- decide_tool_policy: default-allow -----------------------------------------


def test_policy_allows_an_unrestricted_composed_tool():
    # A composed tool with no governing policy is allowed — deny-by-default is gone.
    assert decide_tool_policy(None, "web_search").action is ToolAuthorizationAction.ALLOW
    assert decide_tool_policy({}, "web_search").action is ToolAuthorizationAction.ALLOW


def test_policy_deny_beats_allowlist_and_approval():
    policy = {
        "tools": {"allowed": ["*"], "denied": ["shell_exec"]},
        "approval": {"requires_human_approval": True},
    }

    assert decide_tool_policy(policy, "shell_exec").action is ToolAuthorizationAction.DENY


def test_policy_escalation_requires_approval():
    policy = {"approval": {"escalation_rules": ["shell_exec"]}}

    assert decide_tool_policy(policy, "shell_exec").action is (
        ToolAuthorizationAction.REQUIRE_APPROVAL
    )


def test_a_non_empty_allowlist_still_restricts():
    policy = {"tools": {"allowed": ["web_*"]}}

    assert decide_tool_policy(policy, "web_search").action is ToolAuthorizationAction.ALLOW
    assert decide_tool_policy(policy, "shell_exec").action is ToolAuthorizationAction.DENY


# --- authorize_tool_invocation: task path is policy-only ------------------------


@pytest.mark.asyncio
async def test_task_path_never_consults_the_graph(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()

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
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_path_ignores_a_graph_that_would_deny(monkeypatch):
    # The graph's opinion no longer overrides the snapshot on task paths. A
    # policy-allowed tool runs even if a stale graph grant is absent.
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()
    openfga.check.return_value = CheckResult(allowed=False)

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="shell",
            tool_args={},
            user_id="u1",
            workspace_id="ws-1",
            effective_policy=None,
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.ALLOW
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_path_denies_a_policy_denied_tool(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="shell",
            tool_args={},
            user_id="u1",
            workspace_id="ws-1",
            effective_policy={"tools": {"denied": ["shell"]}},
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.DENY
    openfga.check.assert_not_awaited()


# --- MCP proxy path (policy_required=False): the graph is the only control -------


@pytest.mark.asyncio
async def test_proxy_allows_when_graph_allows(monkeypatch):
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


@pytest.mark.asyncio
async def test_proxy_denies_when_graph_denies(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()
    openfga.check.return_value = CheckResult(allowed=False)

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

    assert decision.action is ToolAuthorizationAction.DENY
    assert decision.reason == "OpenFGA denied this tool invocation"


@pytest.mark.asyncio
async def test_proxy_denies_when_graph_disabled(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "disabled")
    get_settings.cache_clear()

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="github.create_issue",
            tool_args={"repo": "acme/app"},
            user_id="u1",
            workspace_id="ws-1",
            policy_required=False,
        )
    )

    assert decision.action is ToolAuthorizationAction.DENY
    assert decision.reason == "OpenFGA tool authorization is disabled"


@pytest.mark.asyncio
async def test_proxy_requires_user_id(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="github.create_issue",
            tool_args={"repo": "acme/app"},
            workspace_id="ws-1",
            policy_required=False,
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.DENY
    assert decision.reason == "missing user_id for tool authorization"
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_proxy_requires_workspace_id(monkeypatch):
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "openfga")
    get_settings.cache_clear()
    openfga = AsyncMock()

    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="github.create_issue",
            tool_args={"repo": "acme/app"},
            user_id="u1",
            policy_required=False,
        ),
        openfga_client=openfga,
    )

    assert decision.action is ToolAuthorizationAction.DENY
    assert decision.reason == "missing workspace_id for tool authorization"
    openfga.check.assert_not_awaited()
