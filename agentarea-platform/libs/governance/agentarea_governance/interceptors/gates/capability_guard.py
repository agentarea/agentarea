"""CapabilityGuard — checks whether the requested tool is allowed for this agent."""

from __future__ import annotations

import fnmatch
from typing import Any

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult


class CapabilityGuard:
    """Gate interceptor that enforces tool allow/deny lists per agent.

    Config is read from execution_state["tools_config"] which should contain:
        {"allowed": ["tool_a", "tool_b"]} — whitelist (only these allowed)
        {"denied": ["tool_x"]}            — blacklist (all except these)

    Supports glob patterns: "web_*" matches "web_search", "web_fetch", etc.
    If no config is present, defaults to ALLOW (open by default).
    """

    @property
    def name(self) -> str:
        return "capability_guard"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.GATE

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        tools_config: dict[str, Any] = context.execution_state.get("tools_config", {})

        if not tools_config:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no capability config — open by default",
            )

        action_name = context.action_name

        denied = tools_config.get("denied", [])
        if denied and _matches_any(action_name, denied):
            return InterceptorResult(
                action=InterceptorAction.DENY,
                interceptor_name=self.name,
                reason=f"tool '{action_name}' is in denied tools list",
            )

        allowed = tools_config.get("allowed", [])
        if allowed and not _matches_any(action_name, allowed):
            return InterceptorResult(
                action=InterceptorAction.DENY,
                interceptor_name=self.name,
                reason=f"tool '{action_name}' not in allowed tools",
            )

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason="tool allowed",
        )


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
