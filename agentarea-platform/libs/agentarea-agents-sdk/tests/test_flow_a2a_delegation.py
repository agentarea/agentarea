"""Flow test: A2A_DELEGATION — coordinator delegates work to a specialist via the A2A tool.

Pattern: SDK-level hermetic test. A2AAgentTool is the production component that
implements the delegate_to_<name> mechanism. The HTTP transport is mocked so no
live infra is required.

Flow exercised:
  1. Coordinator holds a delegate_to_specialist A2AAgentTool (name / schema).
  2. Coordinator calls tool.execute(message=...) — simulates LLM invoking the tool.
  3. Tool sends a JSON-RPC message/send request to the specialist's A2A endpoint.
  4. Specialist A2A endpoint returns a completed task with text artifacts.
  5. Tool returns success=True with the specialist's result text.
  6. Coordinator incorporates the result — asserted via the returned envelope.
"""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agentarea_common.testing.flows import MainFlow

from agentarea_agents_sdk.tools.a2a_agent_tool import A2AAgentTool, _sanitize_tool_name

_SPECIALIST_NAME = "data_analyst"
_SPECIALIST_URL = "http://specialist.internal/a2a/rpc"
_SPECIALIST_RESULT = "Analysis complete: revenue up 12% QoQ."


def _make_specialist_response(result_text: str) -> dict:
    """Build a well-formed A2A JSON-RPC response carrying a text artifact."""
    return {
        "jsonrpc": "2.0",
        "id": "req-1",
        "result": {
            "id": "task-specialist-1",
            "status": {"state": "completed"},
            "artifacts": [
                {
                    "parts": [{"kind": "text", "text": result_text}],
                }
            ],
        },
    }


def _mock_http_client(response_body: dict, status_code: int = 200) -> tuple:
    """Return (patcher, mock_client) that injects a fixed HTTP response."""
    mock_response = httpx.Response(status_code, json=response_body)
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    patcher = patch(
        "agentarea_agents_sdk.tools.a2a_agent_tool.httpx.AsyncClient",
        return_value=mock_client,
    )
    return patcher, mock_client


@pytest.mark.flow(MainFlow.A2A_DELEGATION)
class TestA2ADelegationFlow:
    """Hermetic flow: coordinator delegates to specialist and incorporates result."""

    def setup_method(self):
        self.tool = A2AAgentTool(
            agent_name=_SPECIALIST_NAME,
            agent_description="Analyses revenue data and produces reports.",
            a2a_url=_SPECIALIST_URL,
            auth_token="coord-token",
        )

    # ------------------------------------------------------------------
    # 1. Tool identity — coordinator sees the right delegate_to_* name
    # ------------------------------------------------------------------

    def test_tool_name_matches_delegate_to_convention(self):
        assert self.tool.name == f"delegate_to_{_SPECIALIST_NAME}"
        assert self.tool.name == _sanitize_tool_name(_SPECIALIST_NAME)

    def test_tool_schema_exposes_message_parameter(self):
        schema = self.tool.get_schema()
        assert "message" in schema["parameters"]["properties"]
        assert schema["parameters"]["required"] == ["message"]

    def test_openai_function_definition_is_valid(self):
        defn = self.tool.get_openai_function_definition()
        assert defn["type"] == "function"
        fn = defn["function"]
        assert fn["name"] == f"delegate_to_{_SPECIALIST_NAME}"
        assert "parameters" in fn

    # ------------------------------------------------------------------
    # 2. Full delegation round-trip: message sent, specialist result returned
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delegation_round_trip_returns_specialist_result(self):
        """Core flow: coordinator invokes tool, specialist replies, result incorporated."""
        patcher, mock_client = _mock_http_client(
            _make_specialist_response(_SPECIALIST_RESULT)
        )

        with patcher:
            result = await self.tool.execute(
                message="Analyse Q1 revenue data and summarise findings."
            )

        # Coordinator receives a success envelope with the specialist's text.
        assert result["success"] is True
        assert result["error"] is None
        assert result["result"] == _SPECIALIST_RESULT
        assert result["task_id"] == "task-specialist-1"
        assert result["task_state"] == "completed"

        # The outbound request must be a valid A2A message/send JSON-RPC call.
        mock_client.post.assert_called_once()
        call = mock_client.post.call_args
        url = call.args[0] if call.args else call.kwargs.get("url", call[0][0])
        assert url == _SPECIALIST_URL
        body = json.loads(call.kwargs.get("content") or call[1].get("content"))
        assert body["method"] == "message/send"
        assert body["jsonrpc"] == "2.0"
        parts = body["params"]["message"]["parts"]
        assert any("revenue" in p.get("text", "") for p in parts)

    @pytest.mark.asyncio
    async def test_auth_token_forwarded_to_specialist(self):
        """Coordinator's bearer token must be forwarded in the Authorization header."""
        patcher, mock_client = _mock_http_client(
            _make_specialist_response(_SPECIALIST_RESULT)
        )

        with patcher:
            await self.tool.execute(message="Summarise Q2 data.")

        call = mock_client.post.call_args
        headers = call.kwargs.get("headers") or call[1].get("headers")
        assert headers["Authorization"] == "Bearer coord-token"

    # ------------------------------------------------------------------
    # 3. Specialist failure surfaces to coordinator (not silently lost)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_specialist_rpc_error_surfaced_to_coordinator(self):
        """A JSON-RPC error from the specialist is returned as success=False."""
        error_body = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "error": {"code": -32000, "message": "Specialist overloaded"},
        }
        patcher, _ = _mock_http_client(error_body)

        with patcher:
            result = await self.tool.execute(message="Analyse data.")

        assert result["success"] is False
        assert "Specialist overloaded" in result["error"]

    @pytest.mark.asyncio
    async def test_specialist_http_failure_raises_tool_error(self):
        """HTTP 503 from specialist endpoint raises ToolExecutionError."""
        from agentarea_agents_sdk.tools.base_tool import ToolExecutionError

        patcher, _ = _mock_http_client({}, status_code=503)

        with patcher, pytest.raises(ToolExecutionError, match="HTTP 503"):
            await self.tool.execute(message="Analyse data.")

    # ------------------------------------------------------------------
    # 4. Multiple artifact parts are concatenated for coordinator
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_multi_part_specialist_result_concatenated(self):
        """Multiple text parts from specialist are joined into one string."""
        body = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "result": {
                "id": "task-2",
                "status": {"state": "completed"},
                "artifacts": [
                    {
                        "parts": [
                            {"kind": "text", "text": "Part A."},
                            {"kind": "text", "text": "Part B."},
                        ]
                    }
                ],
            },
        }
        patcher, _ = _mock_http_client(body)

        with patcher:
            result = await self.tool.execute(message="Give me the full report.")

        assert result["success"] is True
        assert result["result"] == "Part A.\nPart B."
