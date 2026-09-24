"""A2A Agent Tool — delegates tasks to another agent via A2A protocol."""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import A2AClientError, A2AClientTimeoutError, Client, ClientConfig, ClientFactory
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    Task,
    TaskState,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from a2a.utils.errors import A2AError
from google.protobuf.json_format import MessageToDict

from .base_tool import BaseTool, ToolExecutionError

logger = logging.getLogger(__name__)

A2A_CALL_TIMEOUT = 120.0
_TERMINAL_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
    }
)
# Polling budget for delegation: stay under the 120s activity timeout.
_POLL_TOTAL_BUDGET = 110.0
_POLL_INTERVAL = 2.0

PaymentHandler = Callable[..., Awaitable[dict[str, Any] | None]]
# Headers httpx derives from the request itself; the payment handler re-sends
# the body, so replaying them would describe a different request.
_NON_REPLAYABLE_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "accept-encoding"}
)


def _sanitize_tool_name(agent_name: str) -> str:
    """Convert agent name to a valid tool function name."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", agent_name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"agent_{sanitized}"
    return f"delegate_to_{sanitized}"


class _PaymentTransport(httpx.AsyncBaseTransport):
    """Settle ``402 Payment Required`` below the A2A client.

    Payment is an HTTP concern the SDK client has no hook for, so the 402 is
    handed to the payment handler here and, once paid, the paid response is
    returned to the client as if it were the original one.
    """

    def __init__(
        self, inner: httpx.AsyncBaseTransport, payment_handler: PaymentHandler, tool_name: str
    ):
        self._inner = inner
        self._payment_handler = payment_handler
        self._tool_name = tool_name
        self.payment_result: dict[str, Any] | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if response.status_code != 402:
            return response

        response_body = (await response.aread()).decode("utf-8", errors="replace")
        request_body = request.content
        result = await self._payment_handler(
            url=str(request.url),
            method=request.method,
            request_headers={
                name: value
                for name, value in request.headers.items()
                if name.lower() not in _NON_REPLAYABLE_HEADERS
            },
            request_body=json.loads(request_body) if request_body else None,
            response_status=response.status_code,
            response_headers=dict(response.headers),
            response_body=response_body,
            tool_name=self._tool_name,
        )
        self.payment_result = result
        if result and result.get("success"):
            paid_status = int(result.get("response_status") or 0)
            if 200 <= paid_status < 300:
                return httpx.Response(
                    paid_status,
                    content=str(result.get("response_body") or "").encode(),
                    headers={"content-type": "application/json"},
                )
        return httpx.Response(
            402,
            content=response_body.encode(),
            headers={"content-type": response.headers.get("content-type", "text/plain")},
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


class A2AAgentTool(BaseTool):
    """Tool that delegates a task to another agent via the A2A protocol.

    Sends ``SendMessage`` through the official A2A SDK client to the target's
    JSON-RPC endpoint, then polls ``GetTask`` until the task is terminal.
    """

    def __init__(
        self,
        agent_name: str,
        agent_description: str,
        a2a_url: str,
        auth_token: str | None = None,
        payment_handler: PaymentHandler | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._agent_name = agent_name
        self._agent_description = agent_description
        self._a2a_url = a2a_url
        self._auth_token = auth_token
        self._payment_handler = payment_handler
        self._http_transport = http_transport

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

    def _client(self, transport: httpx.AsyncBaseTransport) -> Client:
        headers = {"Authorization": f"Bearer {self._auth_token}"} if self._auth_token else {}
        httpx_client = httpx.AsyncClient(
            transport=transport, timeout=A2A_CALL_TIMEOUT, headers=headers
        )
        # The endpoint is configured, not discovered: describe it as the card
        # would, so the client speaks JSON-RPC v1.0 to exactly that URL.
        card = AgentCard(
            name=self._agent_name,
            supported_interfaces=[
                AgentInterface(
                    url=self._a2a_url,
                    protocol_binding=TransportProtocol.JSONRPC.value,
                    protocol_version=PROTOCOL_VERSION_CURRENT,
                )
            ],
            capabilities=AgentCapabilities(streaming=False),
        )
        config = ClientConfig(streaming=False, polling=True, httpx_client=httpx_client)
        return ClientFactory(config).create(card)

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Send SendMessage to the target agent and return the result."""
        message_text = kwargs.get("message", "")
        if not message_text:
            raise ToolExecutionError(self.name, "message is required")

        transport: httpx.AsyncBaseTransport = self._http_transport or httpx.AsyncHTTPTransport()
        payments: _PaymentTransport | None = None
        if self._payment_handler:
            payments = _PaymentTransport(transport, self._payment_handler, self.name)
            transport = payments

        request = SendMessageRequest(
            message=Message(
                message_id=uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=message_text)]
            )
        )
        try:
            async with self._client(transport) as client:
                task: Task | None = None
                async for response in client.send_message(request):
                    if response.HasField("message"):
                        texts = self._extract_parts_text(response.message.parts)
                        return self._success("\n".join(texts) or "(No output from agent)")
                    task = response.task
                if task is None:
                    raise ToolExecutionError(self.name, "A2A agent returned no task")
                payment = payments.payment_result if payments else None

                if task.status.state not in _TERMINAL_STATES:
                    task = await self._poll_until_terminal(client, task)
                return self._success(
                    self._extract_task_result(task),
                    task_id=task.id,
                    task_state=TaskState.Name(task.status.state),
                    payment=payment,
                )
        except ToolExecutionError:
            raise
        except A2AClientTimeoutError as e:
            raise ToolExecutionError(
                self.name, f"A2A call to '{self._agent_name}' timed out"
            ) from e
        except A2AClientError as e:
            cause = e.__cause__
            if isinstance(cause, httpx.HTTPStatusError):
                status = cause.response.status_code
                if status == 402 and payments and payments.payment_result:
                    payment_error = payments.payment_result.get("error") or "payment failed"
                    raise ToolExecutionError(
                        self.name, f"A2A payment failed: {payment_error}"
                    ) from e
                raise ToolExecutionError(self.name, f"A2A request failed with HTTP {status}") from e
            if cause is not None:
                raise ToolExecutionError(self.name, str(e), e) from e
            # A JSON-RPC error code the SDK has no type for, answered by the agent.
            return self._failure(str(e))
        except A2AError as e:
            # A JSON-RPC error the remote agent answered with.
            return self._failure(e.message)
        except Exception as e:
            logger.error(f"A2A agent tool call failed: {e}", exc_info=True)
            raise ToolExecutionError(self.name, str(e), e) from e

    def _success(self, result: str, **extra: Any) -> dict[str, Any]:
        return {"success": True, "result": result, "error": None, "tool_name": self.name, **extra}

    def _failure(self, error: str) -> dict[str, Any]:
        return {"success": False, "result": "", "error": error, "tool_name": self.name}

    async def _poll_until_terminal(self, client: Client, task: Task) -> Task:
        """Poll GetTask until the task is terminal or the budget elapses.

        Returns the latest task seen; a poll that fails is logged and retried.
        """
        elapsed = 0.0
        while elapsed < _POLL_TOTAL_BUDGET:
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL
            try:
                task = await client.get_task(GetTaskRequest(id=task.id))
            except A2AError:
                logger.warning(f"A2A poll for task {task.id} failed", exc_info=True)
                continue
            if task.status.state in _TERMINAL_STATES:
                return task

        logger.warning(f"A2A delegation to '{self._agent_name}' did not finish within budget")
        return task

    @staticmethod
    def _extract_parts_text(parts: Any) -> list[str]:
        texts: list[str] = []
        for part in parts:
            kind = part.WhichOneof("content")
            if kind == "text":
                texts.append(part.text)
            elif kind == "data":
                texts.append(json.dumps(MessageToDict(part.data)))
        return texts

    def _extract_task_result(self, task: Task) -> str:
        """Readable text from a task's artifacts, else from its status message."""
        texts: list[str] = []
        for artifact in task.artifacts:
            texts.extend(self._extract_parts_text(artifact.parts))
        if not texts and task.status.HasField("message"):
            texts = [
                part.text
                for part in task.status.message.parts
                if part.WhichOneof("content") == "text"
            ]
        return "\n".join(texts) if texts else "(No output from agent)"
