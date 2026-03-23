"""RegexDetectionEngine — pattern matching with zero external dependencies."""

from __future__ import annotations

import re
from typing import Any

from ..domain.models import DetectionFinding

# Default pattern sets by category
DEFAULT_PATTERNS: dict[str, list[str]] = {
    "pii.email": [r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"],
    "pii.phone": [r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"],
    "pii.ssn": [r"\b\d{3}-\d{2}-\d{4}\b"],
    "credential.api_key": [
        r"\b(?:sk|pk|api[_-]?key)[_-][A-Za-z0-9]{16,}\b",
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b",
    ],
    "credential.bearer_token": [r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"],
    "internal.file_path": [r"(?:/(?:home|Users|var|etc|tmp)/[^\s\"'<>|]+)"],
    "injection.override": [
        r"(?i)ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions",
        r"(?i)you\s+are\s+now\s+(?:a|an)\b",
        r"(?i)forget\s+(?:all\s+)?(?:previous|your)\s+(?:instructions|rules)",
        r"(?i)disregard\s+(?:all\s+)?(?:previous|prior|above)",
    ],
    "injection.role_impersonation": [
        r"(?i)\bsystem\s*:\s",
        r"(?i)\[SYSTEM\]",
        r"(?i)<<\s*SYS\s*>>",
    ],
}


class RegexDetectionEngine:
    """Detection engine using compiled regex patterns.

    Zero external dependencies — uses Python's `re` module only.
    All matches have confidence=1.0 (exact pattern match).
    """

    def __init__(
        self,
        patterns: dict[str, list[str]] | None = None,
    ) -> None:
        source = patterns or DEFAULT_PATTERNS
        self._compiled: dict[str, list[re.Pattern[str]]] = {}
        for category, pattern_list in source.items():
            self._compiled[category] = [re.compile(p) for p in pattern_list]

    async def detect(
        self, content: str, config: dict[str, Any] | None = None
    ) -> list[DetectionFinding]:
        findings: list[DetectionFinding] = []
        categories = config.get("categories") if config else None

        for category, compiled_patterns in self._compiled.items():
            if categories and category not in categories:
                continue
            for pattern in compiled_patterns:
                for match in pattern.finditer(content):
                    findings.append(
                        DetectionFinding(
                            category=category,
                            matched_text=match.group(),
                            span=(match.start(), match.end()),
                            confidence=1.0,
                            engine_name="regex",
                        )
                    )
        return findings
