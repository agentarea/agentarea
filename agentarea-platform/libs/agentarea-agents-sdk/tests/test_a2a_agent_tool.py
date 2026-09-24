"""Tests for A2AAgentTool."""

import json

import httpx
import pytest
from a2a.types import Artifact, Message, Part, Role, Task, TaskState, TaskStatus
from google.protobuf.json_format import MessageToDict

from agentarea_agents_sdk.tools import a2a_agent_tool
from agentarea_agents_sdk.tools.a2a_agent_tool import (
    A2AAgentTool,
    _sanitize_tool_name,
)
from agentarea_agents_sdk.tools.base_tool import ToolExecutionError

A2A_URL = "http://localhost:9000/a2a/rpc"


def _task(state: TaskState.ValueType, *texts: str, task_id: str = "task-1") -> dict:
    task = Task(id=task_id, context_id="ctx", status=TaskStatus(state=state))
    if texts:
        task.artifacts.append(Artifact(artifact_id="a", parts=[Part(text=t) for t in texts]))
    return MessageToDict(task)


def _result(request: httpx.Request, result: dict) -> httpx.Response:
    return httpx.Response(
        200, json={"jsonrpc": "2.0", "id": json.loads(request.content)["id"], "result": result}
    )


def _transport(*replies):
    """A mock A2A endpoint answering each JSON-RPC call with the next reply.

    A reply is a callable ``(request) -> httpx.Response``; ``seen`` records the
    requests in order.
    """
    seen: list[httpx.Request] = []
    queue = list(replies)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)(request)

    return httpx.MockTransport(handle), seen


def _send_result(state=TaskState.TASK_STATE_COMPLETED, *texts: str):
    return lambda request: _result(request, {"task": _task(state, *texts)})


def _get_result(state=TaskState.TASK_STATE_COMPLETED, *texts: str):
    return lambda request: _result(request, _task(state, *texts))


class TestSanitizeToolName:
    """Tests for _sanitize_tool_name helper."""

    def test_simple_name(self):
        assert _sanitize_tool_name("researcher") == "delegate_to_researcher"

    def test_name_with_spaces(self):
        assert _sanitize_tool_name("my agent") == "delegate_to_my_agent"

    def test_name_with_special_chars(self):
        assert _sanitize_tool_name("agent-v2.0!") == "delegate_to_agent_v2_0"

    def test_name_starting_with_digit(self):
        assert _sanitize_tool_name("123bot") == "delegate_to_agent_123bot"

    def test_empty_name(self):
        assert _sanitize_tool_name("") == "delegate_to_agent_"

    def test_only_special_chars(self):
        # All chars stripped, empty -> prepend agent_
        assert _sanitize_tool_name("---") == "delegate_to_agent_"

    def test_consecutive_underscores_collapsed(self):
        assert _sanitize_tool_name("a  b") == "delegate_to_a_b"


class TestA2AAgentToolProperties:
    """Tests for A2AAgentTool name, description, schema."""

    def setup_method(self):
        self.tool = A2AAgentTool(
            agent_name="researcher",
            agent_description="Searches the web for information.",
            a2a_url=A2A_URL,
        )

    def test_name(self):
        assert self.tool.name == "delegate_to_researcher"

    def test_description(self):
        assert "researcher" in self.tool.description
        assert "Searches the web" in self.tool.description

    def test_schema_has_message_param(self):
        schema = self.tool.get_schema()
        params = schema["parameters"]
        assert params["type"] == "object"
        assert "message" in params["properties"]
        assert params["required"] == ["message"]

    def test_openai_function_definition(self):
        defn = self.tool.get_openai_function_definition()
        assert defn["type"] == "function"
        assert defn["function"]["name"] == "delegate_to_researcher"
        assert "parameters" in defn["function"]


def _tool(transport, **kwargs) -> A2AAgentTool:
    return A2AAgentTool(
        agent_name="researcher",
        agent_description="Searches the web.",
        a2a_url=A2A_URL,
        http_transport=transport,
        **kwargs,
    )


class TestA2AAgentToolExecute:
    """Tests for A2AAgentTool.execute()."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        transport, _ = _transport(_send_result(TaskState.TASK_STATE_COMPLETED, "The answer is 42."))

        result = await _tool(transport).execute(message="What is the meaning of life?")

        assert result["success"] is True
        assert result["result"] == "The answer is 42."
        assert result["task_id"] == "task-1"
        assert result["task_state"] == "TASK_STATE_COMPLETED"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_execute_sends_a_v1_send_message_with_bearer(self):
        transport, seen = _transport(_send_result())

        await _tool(transport, auth_token="test-token").execute(message="hello")

        [request] = seen
        assert str(request.url) == A2A_URL
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["A2A-Version"] == "1.0"
        body = json.loads(request.content)
        assert body["method"] == "SendMessage"
        message = body["params"]["message"]
        assert message["role"] == "ROLE_USER"
        assert message["messageId"]
        assert message["parts"] == [{"text": "hello"}]
        assert body["params"]["configuration"]["returnImmediately"] is True

    @pytest.mark.asyncio
    async def test_execute_polls_until_the_task_is_terminal(self, monkeypatch):
        monkeypatch.setattr(a2a_agent_tool, "_POLL_INTERVAL", 0.0)
        transport, seen = _transport(
            _send_result(TaskState.TASK_STATE_SUBMITTED),
            _get_result(TaskState.TASK_STATE_WORKING),
            _get_result(TaskState.TASK_STATE_COMPLETED, "done"),
        )

        result = await _tool(transport).execute(message="hello")

        assert [json.loads(r.content)["method"] for r in seen] == [
            "SendMessage",
            "GetTask",
            "GetTask",
        ]
        assert json.loads(seen[1].content)["params"] == {"id": "task-1"}
        assert result["result"] == "done"
        assert result["task_state"] == "TASK_STATE_COMPLETED"

    @pytest.mark.asyncio
    async def test_execute_returns_a_direct_message_reply(self):
        reply = Message(message_id="m", role=Role.ROLE_AGENT, parts=[Part(text="hi there")])
        transport, _ = _transport(
            lambda request: _result(request, {"message": MessageToDict(reply)})
        )

        result = await _tool(transport).execute(message="hello")

        assert result["success"] is True
        assert result["result"] == "hi there"

    @pytest.mark.asyncio
    async def test_execute_rpc_error(self):
        transport, _ = _transport(
            lambda request: httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": json.loads(request.content)["id"],
                    "error": {"code": -32000, "message": "Agent busy"},
                },
            )
        )

        result = await _tool(transport).execute(message="hello")

        assert result["success"] is False
        assert "Agent busy" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_http_error(self):
        transport, _ = _transport(lambda request: httpx.Response(500))

        with pytest.raises(ToolExecutionError, match="HTTP 500"):
            await _tool(transport).execute(message="hello")

    @pytest.mark.asyncio
    async def test_execute_paid_a2a_retries_via_payment_handler(self):
        payment_calls = []

        async def payment_handler(**kwargs):
            payment_calls.append(kwargs)
            body = kwargs["request_body"]
            return {
                "success": True,
                "protocol": "mpp",
                "amount_usd": 0.25,
                "recipient": "merchant",
                "response_status": 200,
                "response_body": json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {
                            "task": _task(
                                TaskState.TASK_STATE_COMPLETED, "paid result", task_id="paid-task"
                            )
                        },
                    }
                ),
                "protocol_metadata": {"payment_method": "charge"},
            }

        transport, _ = _transport(
            lambda request: httpx.Response(
                402, headers={"WWW-Authenticate": "Payment test-challenge"}, text="payment required"
            )
        )

        result = await _tool(
            transport, auth_token="test-token", payment_handler=payment_handler
        ).execute(message="hello")

        assert result["success"] is True
        assert result["result"] == "paid result"
        assert result["payment"]["protocol"] == "mpp"
        assert result["payment"]["amount_usd"] == 0.25
        [call] = payment_calls
        assert call["response_status"] == 402
        assert call["response_body"] == "payment required"
        assert call["response_headers"]["www-authenticate"] == "Payment test-challenge"
        assert call["tool_name"] == "delegate_to_researcher"
        assert call["request_body"]["method"] == "SendMessage"
        assert call["request_headers"]["authorization"] == "Bearer test-token"
        assert "content-length" not in call["request_headers"]

    @pytest.mark.asyncio
    async def test_execute_paid_a2a_surfaces_payment_failure(self):
        async def payment_handler(**kwargs):
            return {
                "success": False,
                "protocol": "x402",
                "amount_usd": 10.0,
                "recipient": "merchant",
                "error": "Payment exceeds budget",
            }

        transport, _ = _transport(
            lambda request: httpx.Response(402, headers={"PAYMENT-REQUIRED": "{}"})
        )

        with pytest.raises(ToolExecutionError, match="Payment exceeds budget"):
            await _tool(transport, payment_handler=payment_handler).execute(message="hello")

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        def timeout(request):
            raise httpx.ReadTimeout("timed out", request=request)

        transport, _ = _transport(timeout)

        with pytest.raises(ToolExecutionError, match="timed out"):
            await _tool(transport).execute(message="hello")

    @pytest.mark.asyncio
    async def test_execute_empty_message_raises(self):
        with pytest.raises(ToolExecutionError, match="message is required"):
            await _tool(None).execute(message="")


class TestExtractTaskResult:
    """Tests for _extract_task_result edge cases."""

    def setup_method(self):
        self.tool = A2AAgentTool(
            agent_name="test",
            agent_description="test",
            a2a_url="http://localhost/rpc",
        )

    def test_extract_text_artifacts(self):
        task = Task(
            artifacts=[
                Artifact(artifact_id="1", parts=[Part(text="line1")]),
                Artifact(artifact_id="2", parts=[Part(text="line2")]),
            ]
        )
        assert self.tool._extract_task_result(task) == "line1\nline2"

    def test_extract_data_artifact(self):
        part = Part()
        part.data.struct_value.update({"key": "val"})
        task = Task(artifacts=[Artifact(artifact_id="1", parts=[part])])

        assert json.loads(self.tool._extract_task_result(task)) == {"key": "val"}

    def test_fallback_to_status_message(self):
        task = Task(
            status=TaskStatus(
                state=TaskState.TASK_STATE_COMPLETED,
                message=Message(parts=[Part(text="Done via status")]),
            )
        )
        assert self.tool._extract_task_result(task) == "Done via status"

    def test_no_output(self):
        assert self.tool._extract_task_result(Task()) == "(No output from agent)"

    def test_empty_artifacts_no_status(self):
        task = Task(status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED))
        assert self.tool._extract_task_result(task) == "(No output from agent)"
