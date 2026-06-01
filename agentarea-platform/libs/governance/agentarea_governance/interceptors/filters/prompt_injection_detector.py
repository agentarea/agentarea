"""PromptInjectionDetector — screens input for injection attacks."""

from __future__ import annotations

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult
from ...domain.protocols import DetectionEngine

INJECTION_CATEGORIES = [
    "injection.override",
    "injection.role_impersonation",
]

BLOCK_CONFIDENCE_THRESHOLD = 0.7


class PromptInjectionDetector:
    """Filter interceptor that detects prompt injection attacks.

    Delegates detection to a DetectionEngine. Blocks on high-confidence
    findings, warns on low-confidence.
    """

    def __init__(
        self,
        engine: DetectionEngine,
        block_threshold: float = BLOCK_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._engine = engine
        self._block_threshold = block_threshold

    @property
    def name(self) -> str:
        return "prompt_injection_detector"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.FILTER

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        if context.execution_state.get("content_safety", {}).get(
            "prompt_injection_enabled"
        ) is False:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="prompt injection detection disabled by policy",
            )

        content = context.content
        if not content:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no content to scan",
            )

        findings = await self._engine.detect(content, {"categories": INJECTION_CATEGORIES})

        if not findings:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no injection detected",
            )

        high_confidence = [f for f in findings if f.confidence >= self._block_threshold]

        if high_confidence:
            categories = {f.category for f in high_confidence}
            return InterceptorResult(
                action=InterceptorAction.DENY,
                interceptor_name=self.name,
                reason=f"prompt injection detected: {', '.join(categories)}",
                findings=findings,
            )

        return InterceptorResult(
            action=InterceptorAction.WARN,
            interceptor_name=self.name,
            reason="suspicious patterns detected (low confidence)",
            findings=findings,
        )
