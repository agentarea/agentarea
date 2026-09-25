"""CostBudgetGuard — enforces USD budget limits per execution."""

from __future__ import annotations

from decimal import Decimal

from agentarea_common.money import ZERO, serialize_money, to_money

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult

DEFAULT_WARNING_THRESHOLD = 0.8


class CostBudgetGuard:
    """Gate interceptor that enforces USD budget limits.

    Reads from execution_state:
        budget_usd: Money     — total budget
        cost_used: Money      — cost consumed so far

    Returns WARN at warning threshold (default 80%), DENY when exhausted.
    """

    def __init__(self, warning_threshold: float = DEFAULT_WARNING_THRESHOLD) -> None:
        self._warning_threshold = Decimal(str(warning_threshold))

    @property
    def name(self) -> str:
        return "cost_budget_guard"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.GATE

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        budget_usd = to_money(context.execution_state.get("budget_usd"))
        if budget_usd <= ZERO:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no budget configured",
            )

        cost_used = to_money(context.execution_state.get("cost_used"))
        usage_ratio = cost_used / budget_usd

        if cost_used >= budget_usd:
            return InterceptorResult(
                action=InterceptorAction.DENY,
                interceptor_name=self.name,
                reason=f"budget exhausted (${cost_used:.2f}/${budget_usd:.2f})",
                metadata={
                    "cost_used": serialize_money(cost_used),
                    "budget_usd": serialize_money(budget_usd),
                },
            )

        if usage_ratio >= self._warning_threshold:
            return InterceptorResult(
                action=InterceptorAction.WARN,
                interceptor_name=self.name,
                reason=f"budget at {usage_ratio:.0%} (${cost_used:.2f}/${budget_usd:.2f})",
                metadata={
                    "cost_used": serialize_money(cost_used),
                    "budget_usd": serialize_money(budget_usd),
                    "usage_ratio": float(usage_ratio),
                },
            )

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason=f"budget ok (${cost_used:.2f}/${budget_usd:.2f})",
        )
