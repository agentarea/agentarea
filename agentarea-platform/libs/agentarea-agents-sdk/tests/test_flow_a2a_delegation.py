"""Flow test: A2A_DELEGATION — coordinator delegates work to a specialist via the A2A tool.

Pattern: SDK-level hermetic test. A2AAgentTool is the production component that
implements the delegate_to_<name> mechanism. The HTTP transport is mocked so no
live infra is required (``test_a2a_agent_tool_sdk_server`` runs the same tool
against the official SDK server).

Flow exercised:
  1. Coordinator holds a delegate_to_specialist A2AAgentTool (name / schema).
  2. Coordinator calls tool.execute(message=...) — simulates LLM invoking the tool.
  3. Tool sends a JSON-RPC SendMessage request to the specialist's A2A endpoint.
  4. Specialist A2A endpoint returns a completed task with text artifacts.
  5. Tool returns success=True with the specialist's result text.
  6. Coordinator incorporates the result — asserted via the returned envelope.
"""

import json

import httpx
import pytest
from a2a.types import Artifact, Part, Task, TaskState, TaskStatus
from agentarea_common.testing.flows import MainFlow
from google.protobuf.json_format import MessageToDict

from agentarea_agents_sdk.tools.a2a_agent_tool import A2AAgentTool, _sanitize_tool_name

_SPECIALIST_NAME = "data_analyst"
_SPECIALIST_URL = "http://specialist.internal/a2a/rpc"
_SPECIALIST_RESULT = "Analysis complete: revenue up 12% QoQ."


def _make_specialist_response(*texts: str) -> dict:
    """A completed A2A task carrying the specialist's text artifact."""
    task = Task(
        id="task-specialist-1",
        context_id="ctx",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        artifacts=[Artifact(artifact_id="a", parts=[Part(text=t) for t in texts])],
    )
    return {"task": MessageToDict(task)}


def _specialist(result: dict | None = None, *, error: dict | None = None, status_code=200):
    """(transport, seen): a mock specialist endpoint answering one JSON-RPC call."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status_code != 200:
            return httpx.Response(status_code)
        body = {"jsonrpc": "2.0", "id": json.loads(request.content)["id"]}
        body.update({"error": error} if error else {"result": result})
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handle), seen


def _tool(transport) -> A2AAgentTool:
    return A2AAgentTool(
        agent_name=_SPECIALIST_NAME,
        agent_description="Analyses revenue data and produces reports.",
        a2a_url=_SPECIALIST_URL,
        auth_token="coord-token",
        http_transport=transport,
    )


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
        transport, seen = _specialist(_make_specialist_response(_SPECIALIST_RESULT))

        result = await _tool(transport).execute(
            message="Analyse Q1 revenue data and summarise findings."
        )

        # Coordinator receives a success envelope with the specialist's text.
        assert result["success"] is True
        assert result["error"] is None
        assert result["result"] == _SPECIALIST_RESULT
        assert result["task_id"] == "task-specialist-1"
        assert result["task_state"] == "TASK_STATE_COMPLETED"

        # The outbound request must be a valid A2A SendMessage JSON-RPC call.
        [request] = seen
        assert str(request.url) == _SPECIALIST_URL
        body = json.loads(request.content)
        assert body["method"] == "SendMessage"
        assert body["jsonrpc"] == "2.0"
        parts = body["params"]["message"]["parts"]
        assert any("revenue" in p.get("text", "") for p in parts)

    @pytest.mark.asyncio
    async def test_auth_token_forwarded_to_specialist(self):
        """Coordinator's bearer token must be forwarded in the Authorization header."""
        transport, seen = _specialist(_make_specialist_response(_SPECIALIST_RESULT))

        await _tool(transport).execute(message="Summarise Q2 data.")

        assert seen[0].headers["Authorization"] == "Bearer coord-token"

    # ------------------------------------------------------------------
    # 3. Specialist failure surfaces to coordinator (not silently lost)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_specialist_rpc_error_surfaced_to_coordinator(self):
        """A JSON-RPC error from the specialist is returned as success=False."""
        transport, _ = _specialist(error={"code": -32000, "message": "Specialist overloaded"})

        result = await _tool(transport).execute(message="Analyse data.")

        assert result["success"] is False
        assert "Specialist overloaded" in result["error"]

    @pytest.mark.asyncio
    async def test_specialist_http_failure_raises_tool_error(self):
        """HTTP 503 from specialist endpoint raises ToolExecutionError."""
        from agentarea_agents_sdk.tools.base_tool import ToolExecutionError

        transport, _ = _specialist(status_code=503)

        with pytest.raises(ToolExecutionError, match="HTTP 503"):
            await _tool(transport).execute(message="Analyse data.")

    # ------------------------------------------------------------------
    # 4. Multiple artifact parts are concatenated for coordinator
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_multi_part_specialist_result_concatenated(self):
        """Multiple text parts from specialist are joined into one string."""
        transport, _ = _specialist(_make_specialist_response("Part A.", "Part B."))

        result = await _tool(transport).execute(message="Give me the full report.")

        assert result["success"] is True
        assert result["result"] == "Part A.\nPart B."
