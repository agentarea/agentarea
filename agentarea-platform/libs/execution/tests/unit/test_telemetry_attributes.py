"""What the run, model-call and tool-call metrics count a call under (ADR-0048 §9)."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from agentarea_execution.activities.agent.tools import tool_kind
from agentarea_execution.models import MCPToolRequest, McpToolRoute
from agentarea_execution.telemetry import (
    OTHER_ERROR,
    RunFailureReason,
    ToolKind,
    ToolOutcome,
    _InFlight,
    llm_error_type,
    run_failure_reason,
    tool_failure_outcome,
)


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        ("completed", None, RunFailureReason.NONE),
        ("running", None, RunFailureReason.NONE),
        ("failed", None, RunFailureReason.INTERNAL),
        ("failed", "something_new", RunFailureReason.INTERNAL),
        ("failed", "timeout", RunFailureReason.TIMEOUT),
        ("failed", "provider_out_of_credits", RunFailureReason.PROVIDER),
        ("failed", "iteration_limit", RunFailureReason.LIMIT),
        ("failed", "dependency_unavailable", RunFailureReason.DEPENDENCY),
        ("cancelled", None, RunFailureReason.CANCELLED),
        ("blocked", "workspace_rule_42", RunFailureReason.POLICY),
        ("waiting_for_continuation", "budget_exceeded", RunFailureReason.LIMIT),
    ],
)
def test_run_failure_reason_is_a_closed_value(status, reason, expected):
    assert run_failure_reason(status, reason) is expected


def test_run_failure_reasons_stay_within_the_budget():
    assert len(RunFailureReason) <= 12


def test_llm_error_type_is_the_classified_cause():
    request = httpx.Request("POST", "https://provider.example.com/v1/chat")
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError("429", request=request, response=response)

    assert llm_error_type(error) == "rate_limited"
    assert llm_error_type(ValueError("unexpected")) == OTHER_ERROR
    assert llm_error_type(asyncio.CancelledError()) == "cancelled"


def test_a_raised_tool_call_is_a_timeout_or_a_transport_error():
    assert tool_failure_outcome(TimeoutError()) is ToolOutcome.TIMEOUT
    assert tool_failure_outcome(httpx.ReadTimeout("slow")) is ToolOutcome.TIMEOUT
    assert tool_failure_outcome(httpx.ConnectError("refused")) is ToolOutcome.TRANSPORT_ERROR
    assert tool_failure_outcome(asyncio.CancelledError()) is ToolOutcome.CANCELLED


def _request(**overrides) -> MCPToolRequest:
    return MCPToolRequest(
        tool_name="search",
        tool_args={},
        workspace_id="ws",
        **overrides,
    )


def test_tool_kind_follows_how_the_call_is_routed():
    route = McpToolRoute(instance_id=str(uuid4()), raw_name="search", attachment_ref="srv")

    assert tool_kind(_request(mcp_route=route)) is ToolKind.MCP
    assert tool_kind(_request(openapi_operation_tools={"conn": ["search"]})) is ToolKind.OPENAPI
    assert tool_kind(_request()) is ToolKind.BUILTIN


def test_oldest_in_flight_is_per_kind_and_falls_to_zero_when_done():
    calls = _InFlight()
    first = calls.begin(("mcp", "worker"))
    calls.begin(("builtin", "worker"))

    calls.end(first)
    ages = calls.oldest()

    assert ages[("mcp", "worker")] == 0.0
    assert ages[("builtin", "worker")] >= 0.0
