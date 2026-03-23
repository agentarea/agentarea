"""SemanticGuard — classifies tool call intent for destructive patterns."""

from __future__ import annotations

import re

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult

# High severity — always deny
DENY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("DROP TABLE", re.compile(r"(?i)\bDROP\s+TABLE\b")),
    ("DROP DATABASE", re.compile(r"(?i)\bDROP\s+DATABASE\b")),
    ("rm -rf /", re.compile(r"rm\s+-rf\s+/")),
    ("format disk", re.compile(r"(?i)\bformat\s+[a-z]:\b")),
    ("TRUNCATE TABLE", re.compile(r"(?i)\bTRUNCATE\s+TABLE\b")),
    ("shutdown", re.compile(r"(?i)\bshutdown\s+(?:-h|now|/s)\b")),
]

# Medium severity — escalate for human review
ESCALATE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("DELETE FROM", re.compile(r"(?i)\bDELETE\s+FROM\b")),
    ("UPDATE ... SET", re.compile(r"(?i)\bUPDATE\s+\w+\s+SET\b")),
    ("ALTER TABLE", re.compile(r"(?i)\bALTER\s+TABLE\b")),
    ("rm -rf", re.compile(r"rm\s+-rf\b")),
    ("chmod 777", re.compile(r"chmod\s+777\b")),
]


class SemanticGuard:
    """Gate interceptor that detects destructive tool call patterns.

    High-severity patterns → DENY
    Medium-severity patterns → ESCALATE (route to human)
    """

    @property
    def name(self) -> str:
        return "semantic_guard"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.GATE

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        text = _extract_text(context)
        if not text:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no content to analyze",
            )

        for label, pattern in DENY_PATTERNS:
            if pattern.search(text):
                return InterceptorResult(
                    action=InterceptorAction.DENY,
                    interceptor_name=self.name,
                    reason=f"destructive pattern detected: {label}",
                    metadata={"pattern": label},
                )

        for label, pattern in ESCALATE_PATTERNS:
            if pattern.search(text):
                return InterceptorResult(
                    action=InterceptorAction.ESCALATE,
                    interceptor_name=self.name,
                    reason=f"potentially destructive pattern: {label}",
                    metadata={"pattern": label},
                )

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason="no destructive patterns detected",
        )


def _extract_text(context: InterceptorContext) -> str:
    """Extract searchable text from context."""
    parts = []
    if context.content:
        parts.append(context.content)
    for value in context.action_params.values():
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts)
