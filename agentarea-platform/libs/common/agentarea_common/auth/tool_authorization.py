"""Single PDP for concrete tool invocation authorization."""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "ToolAuthorizationAction",
    "ToolAuthorizationDecision",
    "ToolAuthorizationRequest",
    "any_name_matches",
    "tool_matches_any",
]


class ToolAuthorizationAction(StrEnum):
    """Authorization verdict for a concrete tool invocation."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class ToolAuthorizationRequest:
    """Inputs to the tool invocation PDP.

    The decision is the resolved policy snapshot's verdict for ``tool_name``;
    ``user_id``/``workspace_id`` are carried as request context. ``aliases`` are
    the tool's other names a rule may target (see ``decide_tool_policy``).
    """

    tool_name: str
    tool_args: dict[str, Any]
    user_id: str | None = None
    workspace_id: str | None = None
    effective_policy: dict[str, Any] | None = None
    aliases: Sequence[str] = ()


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
    return decide_tool_policy(request.effective_policy, request.tool_name, aliases=request.aliases)


def decide_tool_policy(
    effective_policy: dict[str, Any] | None,
    tool_name: str,
    *,
    aliases: Sequence[str] = (),
) -> ToolAuthorizationDecision:
    """Evaluate only the task policy portion of a tool invocation decision.

    Default-allow: this function only ever judges a tool the agent is already
    composed with (that is why it is being asked about), so composition is the
    allow. Policy subtracts from it — a ``denied`` match, or an ``allowed``
    allowlist the tool falls outside of, or an approval requirement.

    An *absent* allowlist is "no allowlist in use"; an *empty* one is "no tool
    is permitted". They are distinct values all the way down: the resolver
    treats ``[]`` as a narrowing a lower scope may not widen, and
    ``to_json_dict`` drops ``None`` while keeping ``[]``. Testing truthiness
    here would collapse them again and make the strictest allowlist the one
    that restricts nothing.

    A tool may be known by several names — an MCP tool by the name the model
    calls, its canonical ``mcp:<instance>:<tool>`` id, and the raw name its
    server advertises. A rule naming any of them governs the tool.
    """
    names = (tool_name, *aliases)
    tools = (effective_policy or {}).get("tools") or {}

    denied = tools.get("denied") or []
    if any_name_matches(names, denied):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            f"tool '{tool_name}' is denied by policy",
        )

    allowed = tools.get("allowed")
    if allowed is not None and not any_name_matches(names, allowed):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            f"tool '{tool_name}' is not permitted by the policy allowlist",
        )

    # Patterns, like the two lists above: `approval tool:send_*` is writable and
    # compiles straight into escalation_rules, so matching it exactly would let
    # an approval gate install, render in the UI, and never fire.
    approval = (effective_policy or {}).get("approval") or {}
    if approval.get("requires_human_approval") is True or any_name_matches(
        names, approval.get("escalation_rules") or []
    ):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.REQUIRE_APPROVAL,
            f"tool '{tool_name}' requires approval",
        )

    return ToolAuthorizationDecision(ToolAuthorizationAction.ALLOW, "allowed by task policy")


def tool_matches_any(name: str, patterns: list[str]) -> bool:
    """Whether a tool name matches any policy pattern.

    Every list a policy holds tool names in — denied, allowed, escalation_rules,
    the keys of approvers_by_tool — is matched through here, so one rule spelling
    means the same thing wherever it is read.
    """
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def any_name_matches(names: Sequence[str], patterns: list[str]) -> bool:
    """Whether any of a tool's names matches any policy pattern."""
    return any(tool_matches_any(name, patterns) for name in names)
