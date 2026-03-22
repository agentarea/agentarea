"""ContentPolicyEnforcer — blocks prohibited content categories."""

from __future__ import annotations

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult
from ...domain.protocols import DetectionEngine


class ContentPolicyEnforcer:
    """Filter interceptor that blocks content matching prohibited categories.

    The prohibited categories are configured at construction.
    Delegates detection to a DetectionEngine.
    """

    def __init__(
        self,
        engine: DetectionEngine,
        prohibited_categories: list[str] | None = None,
    ) -> None:
        self._engine = engine
        self._prohibited = set(prohibited_categories or [])

    @property
    def name(self) -> str:
        return "content_policy_enforcer"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.FILTER

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        content = context.content
        if not content:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no content to check",
            )

        if not self._prohibited:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no prohibited categories configured",
            )

        findings = await self._engine.detect(content, {"categories": list(self._prohibited)})

        violations = [f for f in findings if f.category in self._prohibited]

        if violations:
            categories = {f.category for f in violations}
            return InterceptorResult(
                action=InterceptorAction.DENY,
                interceptor_name=self.name,
                reason=f"content policy violation: {', '.join(categories)}",
                findings=violations,
            )

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason="content policy check passed",
        )
