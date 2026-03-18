"""MCPToolSecurityScanner — scans MCP tool definitions for poisoning."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import DetectionFinding, InterceptorContext, InterceptorResult
from ...domain.protocols import DetectionEngine

SUSPICIOUS_PATTERNS = [
    "send data to",
    "exfiltrate",
    "forward to",
    "external-server",
    "curl ",
    "wget ",
    "POST http",
]


class MCPToolSecurityScanner:
    """Filter interceptor that scans tool definitions at discovery time.

    Detects:
    - Description injection (hidden instructions in tool descriptions)
    - Rug pulls (tool definition hash changed since last seen)
    """

    def __init__(
        self,
        engine: DetectionEngine | None = None,
        known_hashes: dict[str, str] | None = None,
    ) -> None:
        self._engine = engine
        self._known_hashes = dict(known_hashes or {})

    @property
    def name(self) -> str:
        return "mcp_tool_scanner"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.FILTER

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        content = context.content
        if not content:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="no tool definition to scan",
            )

        findings: list[DetectionFinding] = []

        # Check for suspicious patterns in tool description
        content_lower = content.lower()
        for i, pattern in enumerate(SUSPICIOUS_PATTERNS):
            idx = content_lower.find(pattern.lower())
            if idx >= 0:
                findings.append(
                    DetectionFinding(
                        category="tool_poisoning.description_injection",
                        matched_text=content[idx : idx + len(pattern)],
                        span=(idx, idx + len(pattern)),
                        confidence=0.8,
                        engine_name="builtin",
                    )
                )

        # Delegate to engine if available
        if self._engine:
            engine_findings = await self._engine.detect(content, {})
            findings.extend(engine_findings)

        # Rug-pull detection: compare hash
        tool_name = context.action_name
        current_hash = hashlib.sha256(content.encode()).hexdigest()

        if tool_name in self._known_hashes:
            if self._known_hashes[tool_name] != current_hash:
                findings.append(
                    DetectionFinding(
                        category="tool_poisoning.rug_pull",
                        matched_text=f"hash changed for {tool_name}",
                        span=(0, 0),
                        confidence=0.9,
                        engine_name="builtin",
                    )
                )

        # Update known hash
        self._known_hashes[tool_name] = current_hash

        if not findings:
            return InterceptorResult(
                action=InterceptorAction.ALLOW,
                interceptor_name=self.name,
                reason="tool definition clean",
            )

        # Description injection → DENY, rug pull → WARN
        has_injection = any(
            f.category == "tool_poisoning.description_injection" for f in findings
        )
        if has_injection:
            return InterceptorResult(
                action=InterceptorAction.DENY,
                interceptor_name=self.name,
                reason="tool description injection detected",
                findings=findings,
            )

        return InterceptorResult(
            action=InterceptorAction.WARN,
            interceptor_name=self.name,
            reason="tool definition changed (possible rug pull)",
            findings=findings,
            metadata={"current_hash": current_hash},
        )
