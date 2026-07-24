"""Single PDP for concrete tool invocation authorization."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = ["ToolAuthorizationAction", "ToolAuthorizationRequest", "ToolAuthorizationDecision"]


class ToolAuthorizationAction(StrEnum):
    """Authorization verdict for a concrete tool invocation."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class ToolAuthorizationRequest:
    """Inputs to the tool invocation PDP.

    The decision is the resolved policy snapshot's verdict for ``tool_name``;
    ``user_id``/``workspace_id`` are carried as request context.
    """

    tool_name: str
    tool_args: dict[str, Any]
    user_id: str | None = None
    workspace_id: str | None = None
    effective_policy: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolAuthorizationDecision:
    """PDP result consumed by PEP call sites."""

    action: ToolAuthorizationAction
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action is ToolAuthorizationAction.ALLOW


async def authorize_tool_invocation(
    request: ToolAuthorizationRequest,
) -> ToolAuthorizationDecision:
    """Decide whether a concrete tool invocation may run.

    This is the single runtime PDP: the resolved policy snapshot (composition +
    policy) is authoritative, and disclosure, the workflow gate, and the tool
    activity all read the one answer.
    """
    return decide_tool_policy(request.effective_policy, request.tool_name)


def decide_tool_policy(
    effective_policy: dict[str, Any] | None, tool_name: str
) -> ToolAuthorizationDecision:
    """Evaluate only the task policy portion of a tool invocation decision.

    Default-allow: this function only ever judges a tool the agent is already
    composed with (that is why it is being asked about), so composition is the
    allow. Policy subtracts from it — a ``denied`` match, or a non-empty
    ``allowed`` allowlist the tool falls outside of, or an approval requirement.
    An absent/empty allowlist is "no allowlist in use", not "deny everything";
    restriction is expressed by composing fewer tools or by DENY rules.
    """
    tools = (effective_policy or {}).get("tools") or {}

    denied = tools.get("denied") or []
    if _matches_any(tool_name, denied):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            f"tool '{tool_name}' is denied by policy",
        )

    allowed = tools.get("allowed")
    if allowed and not _matches_any(tool_name, allowed):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            f"tool '{tool_name}' is not permitted by the policy allowlist",
        )

    approval = (effective_policy or {}).get("approval") or {}
    if approval.get("requires_human_approval") is True or tool_name in (
        approval.get("escalation_rules") or []
    ):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.REQUIRE_APPROVAL,
            f"tool '{tool_name}' requires approval",
        )

    return ToolAuthorizationDecision(ToolAuthorizationAction.ALLOW, "allowed by task policy")


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
