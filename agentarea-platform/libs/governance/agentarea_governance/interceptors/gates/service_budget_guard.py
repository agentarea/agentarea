"""ServiceBudgetGuard — enforces service spending budget limits per execution."""

from __future__ import annotations

from decimal import Decimal

from agentarea_common.money import ZERO, serialize_money, to_money

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult

DEFAULT_WARNING_THRESHOLD = 0.8


class ServiceBudgetGuard:
    """Gate interceptor that enforces service spending budget limits.

    Reads from execution_state:
        service_budget_usd: Money     — total service budget
        service_cost_used: Money      — service cost consumed so far

    Returns WARN at warning threshold (default 80%), DENY when exhausted.
    """

    def __init__(self, warning_threshold: float = DEFAULT_WARNING_THRESHOLD) -> None:
        self._warning_threshold = Decimal(str(warning_threshold))

    @property
    def name(self) -> str:
        return "service_budget_guard"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.GATE

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        service_budget_usd = to_money(context.execution_state.get("service_budget_usd"))
        if service_budget_usd <= ZERO:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no service budget configured",
            )

        service_cost_used = to_money(context.execution_state.get("service_cost_used"))
        usage_ratio = service_cost_used / service_budget_usd

        if service_cost_used >= service_budget_usd:
            return InterceptorResult(
                action=InterceptorAction.DENY,
                interceptor_name=self.name,
                reason=f"service budget exhausted (${service_cost_used:.2f}/${service_budget_usd:.2f})",
                metadata={
                    "service_cost_used": serialize_money(service_cost_used),
                    "service_budget_usd": serialize_money(service_budget_usd),
                },
            )

        if usage_ratio >= self._warning_threshold:
            return InterceptorResult(
                action=InterceptorAction.WARN,
                interceptor_name=self.name,
                reason=f"service budget at {usage_ratio:.0%} (${service_cost_used:.2f}/${service_budget_usd:.2f})",
                metadata={
                    "service_cost_used": serialize_money(service_cost_used),
                    "service_budget_usd": serialize_money(service_budget_usd),
                    "usage_ratio": float(usage_ratio),
                },
            )

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason=f"service budget ok (${service_cost_used:.2f}/${service_budget_usd:.2f})",
        )
