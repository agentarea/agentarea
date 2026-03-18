"""TokenBudgetGuard — tracks token consumption per execution."""

from __future__ import annotations

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult

DEFAULT_WARNING_THRESHOLD = 0.85


class TokenBudgetGuard:
    """Gate interceptor that enforces token budget limits.

    Reads from execution_state:
        max_tokens: int       — total token budget
        tokens_used: int      — tokens consumed so far

    Returns WARN at warning threshold (default 85%), DENY when exhausted.
    """

    def __init__(self, warning_threshold: float = DEFAULT_WARNING_THRESHOLD) -> None:
        self._warning_threshold = warning_threshold

    @property
    def name(self) -> str:
        return "token_budget_guard"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.GATE

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        max_tokens = context.execution_state.get("max_tokens")
        if max_tokens is None or max_tokens <= 0:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no token budget configured",
            )

        tokens_used = context.execution_state.get("tokens_used", 0)
        usage_ratio = tokens_used / max_tokens

        if tokens_used >= max_tokens:
            return InterceptorResult(
                action=InterceptorAction.DENY,
                interceptor_name=self.name,
                reason=f"token budget exhausted ({tokens_used}/{max_tokens})",
                metadata={"tokens_used": tokens_used, "max_tokens": max_tokens},
            )

        if usage_ratio >= self._warning_threshold:
            return InterceptorResult(
                action=InterceptorAction.WARN,
                interceptor_name=self.name,
                reason=f"token budget at {usage_ratio:.0%} ({tokens_used}/{max_tokens})",
                metadata={"tokens_used": tokens_used, "max_tokens": max_tokens, "usage_ratio": usage_ratio},
            )

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason=f"token budget ok ({tokens_used}/{max_tokens})",
        )
