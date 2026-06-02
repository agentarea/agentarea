"""OutputSanitizer — redacts PII and credentials from output content."""

from __future__ import annotations

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import DetectionFinding, InterceptorContext, InterceptorResult
from ...domain.protocols import DetectionEngine

PII_CATEGORIES = [
    "pii.email",
    "pii.phone",
    "pii.ssn",
    "credential.api_key",
    "credential.bearer_token",
]

REDACTION_LABELS: dict[str, str] = {
    "pii.email": "[EMAIL_REDACTED]",
    "pii.phone": "[PHONE_REDACTED]",
    "pii.ssn": "[SSN_REDACTED]",
    "credential.api_key": "[API_KEY_REDACTED]",
    "credential.bearer_token": "[TOKEN_REDACTED]",
}


class OutputSanitizer:
    """Filter interceptor that redacts sensitive data from output.

    Delegates detection to a DetectionEngine, then replaces matched
    spans with redaction labels.
    """

    def __init__(self, engine: DetectionEngine) -> None:
        self._engine = engine

    @property
    def name(self) -> str:
        return "output_sanitizer"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.FILTER

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        if (
            context.execution_state.get("content_safety", {}).get("output_sanitizer_enabled")
            is False
        ):
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="output sanitizer disabled by policy",
            )

        content = context.content
        if not content:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no content to sanitize",
            )

        findings = await self._engine.detect(content, {"categories": PII_CATEGORIES})

        if not findings:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no sensitive data detected",
            )

        redacted = _apply_redactions(content, findings)

        return InterceptorResult(
            action=InterceptorAction.MODIFY,
            interceptor_name=self.name,
            reason=f"redacted {len(findings)} sensitive item(s)",
            modified_content=redacted,
            findings=findings,
        )


def _apply_redactions(content: str, findings: list[DetectionFinding]) -> str:
    """Replace matched spans with redaction labels, processing right-to-left."""
    sorted_findings = sorted(findings, key=lambda f: f.span[0], reverse=True)
    result = content
    for finding in sorted_findings:
        start, end = finding.span
        label = REDACTION_LABELS.get(finding.category, f"[{finding.category.upper()}_REDACTED]")
        result = result[:start] + label + result[end:]
    return result
