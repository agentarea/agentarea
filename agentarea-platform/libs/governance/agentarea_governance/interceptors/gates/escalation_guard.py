"""EscalationGuard — routes configured actions to human approval."""

from __future__ import annotations

import fnmatch
from typing import Any

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult


class EscalationGuard:
    """Gate interceptor that routes sensitive actions to human approval.

    Reads escalation rules from execution_state["escalation_rules"]
    which is a list of glob patterns (e.g. ["payment_*", "delete_*"]).
    """

    @property
    def name(self) -> str:
        return "escalation_guard"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.GATE

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        rules: list[str] = context.execution_state.get("escalation_rules", [])

        if not rules:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no escalation rules configured",
            )

        action_name = context.action_name

        if any(fnmatch.fnmatch(action_name, rule) for rule in rules):
            return InterceptorResult(
                action=InterceptorAction.ESCALATE,
                interceptor_name=self.name,
                reason=f"action '{action_name}' requires human approval",
                metadata={"matched_rules": [r for r in rules if fnmatch.fnmatch(action_name, r)]},
            )

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason="no escalation rules matched",
        )
