"""A2A Agent Tool — delegates tasks to another agent via A2A protocol."""

import json
import logging
import re
from typing import Any
from uuid import uuid4

import httpx

from .base_tool import BaseTool, ToolExecutionError

logger = logging.getLogger(__name__)

A2A_CALL_TIMEOUT = 120.0


def _sanitize_tool_name(agent_name: str) -> str:
    """Convert agent name to a valid tool function name."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", agent_name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"agent_{sanitized}"
    return f"delegate_to_{sanitized}"


class A2AAgentTool(BaseTool):
    """Tool that delegates a task to another agent via the A2A protocol.

    Sends a `message/send` JSON-RPC request to the target agent's A2A endpoint
    and returns the completed task result.
    """

    def __init__(
        self,
        agent_name: str,
        agent_description: str,
        a2a_url: str,
        auth_token: str | None = None,
    ):
        self._agent_name = agent_name
        self._agent_description = agent_description
        self._a2a_url = a2a_url
        self._auth_token = auth_token

    @property
    def name(self) -> str:
        return _sanitize_tool_name(self._agent_name)

    @property
    def description(self) -> str:
        return f"Delegate a task to the '{self._agent_name}' agent. {self._agent_description}"

    def get_schema(self) -> dict[str, Any]:
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            f"The task or question to send to the '{self._agent_name}' agent. "
                            "Be specific and provide all necessary context."
                        ),
                    },
                },
                "required": ["message"],
            }
        }

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Send message/send to the target agent and return the result."""
        message_text = kwargs.get("message", "")
        if not message_text:
            raise ToolExecutionError(self.name, "message is required")

        rpc_request = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": message_text}],
                },
            },
        }

        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        try:
            async with httpx.AsyncClient(timeout=A2A_CALL_TIMEOUT) as client:
                response = await client.post(
                    self._a2a_url,
                    content=json.dumps(rpc_request),
                    headers=headers,
                )

            if response.status_code != 200:
                raise ToolExecutionError(
                    self.name,
                    f"A2A request failed with HTTP {response.status_code}",
                )

            rpc_response = response.json()

            if "error" in rpc_response and rpc_response["error"]:
                error_msg = rpc_response["error"].get("message", "Unknown A2A error")
                return {
                    "success": False,
                    "result": "",
                    "error": error_msg,
                    "tool_name": self.name,
                }

            task = rpc_response.get("result", {})
            result_text = self._extract_task_result(task)

            return {
                "success": True,
                "result": result_text,
                "error": None,
                "tool_name": self.name,
                "task_id": task.get("id"),
                "task_state": task.get("status", {}).get("state"),
            }

        except httpx.TimeoutException as e:
            raise ToolExecutionError(
                self.name, f"A2A call to '{self._agent_name}' timed out"
            ) from e
        except ToolExecutionError:
            raise
        except Exception as e:
            logger.error(f"A2A agent tool call failed: {e}")
            raise ToolExecutionError(self.name, str(e), e) from e

    def _extract_task_result(self, task: dict[str, Any]) -> str:
        """Extract readable text from a task's artifacts and status message."""
        parts = []
        for artifact in task.get("artifacts") or []:
            for part in artifact.get("parts") or []:
                if part.get("kind") == "text":
                    parts.append(part["text"])
                elif part.get("kind") == "data":
                    parts.append(json.dumps(part.get("data", {})))

        if not parts:
            status_msg = task.get("status", {}).get("message")
            if status_msg:
                for part in status_msg.get("parts") or []:
                    if part.get("kind") == "text":
                        parts.append(part["text"])

        return "\n".join(parts) if parts else "(No output from agent)"
