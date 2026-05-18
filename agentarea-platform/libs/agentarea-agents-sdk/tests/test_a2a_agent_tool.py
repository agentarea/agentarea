"""Tests for A2AAgentTool."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agentarea_agents_sdk.tools.a2a_agent_tool import (
    A2AAgentTool,
    _sanitize_tool_name,
)
from agentarea_agents_sdk.tools.base_tool import ToolExecutionError


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
            a2a_url="http://localhost:9000/a2a/rpc",
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


class TestA2AAgentToolExecute:
    """Tests for A2AAgentTool.execute()."""

    def setup_method(self):
        self.tool = A2AAgentTool(
            agent_name="researcher",
            agent_description="Searches the web.",
            a2a_url="http://localhost:9000/a2a/rpc",
            auth_token="test-token",
        )

    @pytest.mark.asyncio
    async def test_execute_success(self):
        rpc_response = {
            "jsonrpc": "2.0",
            "id": "abc",
            "result": {
                "id": "task-1",
                "status": {"state": "completed"},
                "artifacts": [
                    {
                        "parts": [
                            {"kind": "text", "text": "The answer is 42."},
                        ]
                    }
                ],
            },
        }
        mock_response = httpx.Response(200, json=rpc_response)

        with patch("agentarea_agents_sdk.tools.a2a_agent_tool.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await self.tool.execute(message="What is the meaning of life?")

        assert result["success"] is True
        assert result["result"] == "The answer is 42."
        assert result["task_id"] == "task-1"
        assert result["task_state"] == "completed"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_execute_sends_auth_header(self):
        rpc_response = {
            "jsonrpc": "2.0",
            "id": "abc",
            "result": {"id": "t1", "status": {"state": "completed"}, "artifacts": []},
        }
        mock_response = httpx.Response(200, json=rpc_response)

        with patch("agentarea_agents_sdk.tools.a2a_agent_tool.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await self.tool.execute(message="hello")

            call_kwargs = mock_client.post.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
            assert headers["Authorization"] == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_execute_rpc_error(self):
        rpc_response = {
            "jsonrpc": "2.0",
            "id": "abc",
            "error": {"code": -32000, "message": "Agent busy"},
        }
        mock_response = httpx.Response(200, json=rpc_response)

        with patch("agentarea_agents_sdk.tools.a2a_agent_tool.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await self.tool.execute(message="hello")

        assert result["success"] is False
        assert result["error"] == "Agent busy"

    @pytest.mark.asyncio
    async def test_execute_http_error(self):
        mock_response = httpx.Response(500)

        with patch("agentarea_agents_sdk.tools.a2a_agent_tool.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ToolExecutionError, match="HTTP 500"):
                await self.tool.execute(message="hello")

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        with patch("agentarea_agents_sdk.tools.a2a_agent_tool.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ToolExecutionError, match="timed out"):
                await self.tool.execute(message="hello")

    @pytest.mark.asyncio
    async def test_execute_empty_message_raises(self):
        with pytest.raises(ToolExecutionError, match="message is required"):
            await self.tool.execute(message="")


class TestExtractTaskResult:
    """Tests for _extract_task_result edge cases."""

    def setup_method(self):
        self.tool = A2AAgentTool(
            agent_name="test",
            agent_description="test",
            a2a_url="http://localhost/rpc",
        )

    def test_extract_text_artifacts(self):
        task = {
            "artifacts": [
                {"parts": [{"kind": "text", "text": "line1"}]},
                {"parts": [{"kind": "text", "text": "line2"}]},
            ]
        }
        assert self.tool._extract_task_result(task) == "line1\nline2"

    def test_extract_data_artifact(self):
        task = {
            "artifacts": [
                {"parts": [{"kind": "data", "data": {"key": "val"}}]},
            ]
        }
        result = self.tool._extract_task_result(task)
        assert json.loads(result) == {"key": "val"}

    def test_fallback_to_status_message(self):
        task = {
            "artifacts": [],
            "status": {
                "state": "completed",
                "message": {
                    "parts": [{"kind": "text", "text": "Done via status"}],
                },
            },
        }
        assert self.tool._extract_task_result(task) == "Done via status"

    def test_no_output(self):
        task = {}
        assert self.tool._extract_task_result(task) == "(No output from agent)"

    def test_empty_artifacts_no_status(self):
        task = {"artifacts": [], "status": {"state": "completed"}}
        assert self.tool._extract_task_result(task) == "(No output from agent)"
