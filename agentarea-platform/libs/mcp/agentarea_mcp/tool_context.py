"""Who a tool call is for, as AgentArea tells a remote MCP server.

The contract is ``docs/reference/mcp-tool-call-context.md``: ``agentarea/*`` keys
in ``params._meta`` of ``tools/call``, mirrored as claims of an HS256 token in
the ``X-AgentArea-Context`` header. The token is the part a server can trust;
``_meta`` alone could have been written by anyone holding the static credential.

The token is signed with a secret the instance's owner set on the connection
(stored like its secret headers, never sent). An instance without one gets
neither ``_meta`` keys nor a token.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import jwt

CONTEXT_HEADER = "X-AgentArea-Context"
PROTOCOL_VERSION = "1"
ISSUER = "agentarea"
TOKEN_TTL_SECONDS = 300
META_PREFIX = "agentarea/"
# The slot the signing secret takes in the instance's secret store entries
# (``mcp_instance_{id}_AGENTAREA_CONTEXT_SECRET``). It is not listed in the
# instance's ``env_vars``, so it is never sent as a header or an env var.
CONTEXT_SECRET_NAME = "AGENTAREA_CONTEXT_SECRET"  # noqa: S105 - a slot name, not a value  # pragma: allowlist secret
# ``json_spec`` flag that says a signing secret is stored, so a call does not
# read the secret store for instances that have none.
CONTEXT_SIGNING_FLAG = "context_signing"
CONTEXT_SECRET_MIN_LENGTH = 32

# progress, total, message — the MCP SDK's progress callback shape.
ProgressCallback = Callable[[float, float | None, str | None], Awaitable[None]]


@dataclass(frozen=True)
class ToolCallContext:
    """The trusted facts about one ``tools/call`` the platform vouches for."""

    task_id: str
    tool_call_id: str
    workspace_id: str
    agent_id: str | None = None
    end_user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def idempotency_key(self) -> str:
        return f"{self.task_id}:{self.tool_call_id}"

    def values(self) -> dict[str, Any]:
        """Claim name -> value, absent optional fields left out."""
        values: dict[str, Any] = {
            "protocol": PROTOCOL_VERSION,
            "task_id": self.task_id,
            "tool_call_id": self.tool_call_id,
            "workspace_id": self.workspace_id,
            "idempotency_key": self.idempotency_key,
        }
        if self.agent_id:
            values["agent_id"] = self.agent_id
        if self.end_user_id:
            values["end_user_id"] = self.end_user_id
        if self.metadata:
            values["metadata"] = self.metadata
        return values


def context_meta(context: ToolCallContext) -> dict[str, Any]:
    """The ``agentarea/*`` keys of ``params._meta``."""
    return {f"{META_PREFIX}{name}": value for name, value in context.values().items()}


def sign_context(
    context: ToolCallContext,
    *,
    secret: str,
    audience: str,
    tool: str,
    now: float | None = None,
) -> str:
    """Mint the ``X-AgentArea-Context`` token for one call to one server's tool."""
    issued_at = int(now if now is not None else time.time())
    claims = {
        **context.values(),
        "iss": ISSUER,
        "aud": audience,
        "iat": issued_at,
        "exp": issued_at + TOKEN_TTL_SECONDS,
        "jti": str(uuid4()),
        "tool": tool,
    }
    return jwt.encode(claims, secret.encode("utf-8"), algorithm="HS256", headers={"typ": "JWT"})


# Task metadata keys an API caller fills when it creates a task (see
# ``TaskCreate`` in the API). They reach every tool call of the task as
# ``agentarea/end_user_id`` and ``agentarea/metadata``. The model cannot set them.
END_USER_ID_KEY = "end_user_id"
APP_METADATA_KEY = "app_metadata"


def call_context_from_task(
    *,
    task_id: str | None,
    tool_call_id: str | None,
    workspace_id: str,
    agent_id: str | None,
    task_metadata: dict[str, Any] | None,
) -> ToolCallContext | None:
    """The context of a call made by a task, or None outside of one."""
    if not task_id or not tool_call_id:
        return None
    task_metadata = task_metadata or {}
    end_user_id = task_metadata.get(END_USER_ID_KEY)
    app_metadata = task_metadata.get(APP_METADATA_KEY)
    return ToolCallContext(
        task_id=task_id,
        tool_call_id=tool_call_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        end_user_id=end_user_id if isinstance(end_user_id, str) and end_user_id else None,
        metadata=dict(app_metadata) if isinstance(app_metadata, dict) else {},
    )
