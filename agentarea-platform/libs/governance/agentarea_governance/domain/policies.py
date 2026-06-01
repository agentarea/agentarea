"""Typed governance policy models and resolver.

The policy core is intentionally small and typed. It produces an immutable
EffectivePolicy snapshot that task creation can persist before workflow start
and that runtime governance can translate into InterceptorContext.execution_state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from agentarea_common.money import Money, to_money
from pydantic import BaseModel, ConfigDict, Field, field_validator

RESOLVER_VERSION = "policy-resolver-v1"


class PolicyValidationError(ValueError):
    """Raised when a lower-scope policy attempts to weaken a higher scope."""


class PolicyScopeType(StrEnum):
    """Supported policy scope types."""

    WORKSPACE = "workspace"
    AGENT = "agent"
    TASK = "task"


class PolicyScope(BaseModel):
    """A concrete policy scope."""

    model_config = ConfigDict(extra="forbid")

    scope_type: PolicyScopeType
    scope_id: str


class BudgetPolicy(BaseModel):
    """Budget-related ceilings."""

    model_config = ConfigDict(extra="forbid")

    monthly_spend_cap_usd: Money | None = None
    run_budget_usd: Money | None = None
    service_budget_usd: Money | None = None


class TokenPolicy(BaseModel):
    """Token-related ceilings."""

    model_config = ConfigDict(extra="forbid")

    max_tokens: int | None = None
    max_tokens_per_call: int | None = None


class ToolsPolicy(BaseModel):
    """MCP tool capability restrictions."""

    model_config = ConfigDict(extra="forbid")

    allowed: list[str] | None = None
    denied: list[str] = Field(default_factory=list)


class ApprovalPolicy(BaseModel):
    """Human approval and escalation requirements."""

    model_config = ConfigDict(extra="forbid")

    requires_human_approval: bool | None = None
    escalation_rules: list[str] = Field(default_factory=list)


class ContentSafetyPolicy(BaseModel):
    """Content-safety governance controls."""

    model_config = ConfigDict(extra="forbid")

    prompt_injection_detection_enabled: bool | None = None
    output_sanitizer_enabled: bool | None = None
    semantic_guard_threshold: int | None = None

    @field_validator("semantic_guard_threshold")
    @classmethod
    def _validate_threshold(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 100:
            raise ValueError("semantic_guard_threshold must be between 0 and 100")
        return value


class PolicyDocument(BaseModel):
    """Source policy document stored per scope."""

    model_config = ConfigDict(extra="forbid")

    budget: BudgetPolicy | None = None
    tokens: TokenPolicy | None = None
    tools: ToolsPolicy | None = None
    approval: ApprovalPolicy | None = None
    content_safety: ContentSafetyPolicy | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize with money values as strings for JSONB/Temporal payloads."""
        return self.model_dump(mode="json", exclude_none=True)


class EffectivePolicy(PolicyDocument):
    """Resolved immutable policy snapshot."""

    source_policy_ids: list[str] = Field(default_factory=list)
    resolver_version: str = RESOLVER_VERSION

    def to_execution_state(self, runtime_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """Translate the typed policy snapshot into the guard execution_state.

        This is the anti-corruption layer between the typed governance policy
        domain and the generic interceptor framework. Monetary values are
        emitted as plain floats because the budget gates perform threshold
        arithmetic (ratio comparisons) against runtime counters — authoritative
        money accounting stays upstream in BudgetTracker. Mixing Decimal with
        float here would raise at the gate and be silently swallowed.
        """
        runtime_state = runtime_state or {}
        state: dict[str, Any] = {}

        if self.budget:
            if self.budget.run_budget_usd is not None:
                state["budget_usd"] = float(to_money(self.budget.run_budget_usd))
            if self.budget.service_budget_usd is not None:
                state["service_budget_usd"] = float(to_money(self.budget.service_budget_usd))

        if self.tokens:
            if self.tokens.max_tokens is not None:
                state["max_tokens"] = self.tokens.max_tokens

        if self.tools:
            state["tools_config"] = {
                "allowed": self.tools.allowed or [],
                "denied": self.tools.denied,
            }

        if self.approval:
            state["escalation_rules"] = self.approval.escalation_rules

        if self.content_safety:
            state["content_safety"] = {
                "prompt_injection_enabled": self.content_safety.prompt_injection_detection_enabled,
                "output_sanitizer_enabled": self.content_safety.output_sanitizer_enabled,
                "semantic_guard_threshold": self.content_safety.semantic_guard_threshold,
            }

        for key in ("cost_used", "service_cost_used"):
            if key in runtime_state:
                state[key] = float(to_money(runtime_state[key]))
        if "tokens_used" in runtime_state:
            state["tokens_used"] = runtime_state["tokens_used"]

        return state


def policy_from_json(data: dict[str, Any] | None) -> PolicyDocument:
    """Build a PolicyDocument from a JSON dict."""
    return PolicyDocument.model_validate(data or {})


def effective_policy_from_json(data: dict[str, Any] | None) -> EffectivePolicy:
    """Build an EffectivePolicy from a JSON dict."""
    return EffectivePolicy.model_validate(data or {})


class PolicyResolver:
    """Resolve source policies into a monotonic EffectivePolicy."""

    def resolve(
        self,
        policies: list[PolicyDocument | None],
        *,
        source_policy_ids: list[str] | None = None,
    ) -> EffectivePolicy:
        current = PolicyDocument()
        for policy in policies:
            if policy is None:
                continue
            self._validate_tightens(current, policy)
            current = self._merge(current, policy)

        return EffectivePolicy(
            **current.model_dump(),
            source_policy_ids=source_policy_ids or [],
            resolver_version=RESOLVER_VERSION,
        )

    def _validate_tightens(self, higher: PolicyDocument, lower: PolicyDocument) -> None:
        self._validate_budget(higher.budget, lower.budget)
        self._validate_tokens(higher.tokens, lower.tokens)
        self._validate_tools(higher.tools, lower.tools)
        self._validate_approval(higher.approval, lower.approval)
        self._validate_content_safety(higher.content_safety, lower.content_safety)

    def _merge(self, higher: PolicyDocument, lower: PolicyDocument) -> PolicyDocument:
        return PolicyDocument(
            budget=self._merge_budget(higher.budget, lower.budget),
            tokens=self._merge_tokens(higher.tokens, lower.tokens),
            tools=self._merge_tools(higher.tools, lower.tools),
            approval=self._merge_approval(higher.approval, lower.approval),
            content_safety=self._merge_content_safety(higher.content_safety, lower.content_safety),
        )

    def _validate_budget(self, higher: BudgetPolicy | None, lower: BudgetPolicy | None) -> None:
        if not higher or not lower:
            return
        for field in ("monthly_spend_cap_usd", "run_budget_usd", "service_budget_usd"):
            higher_value = getattr(higher, field)
            lower_value = getattr(lower, field)
            if higher_value is not None and lower_value is not None:
                if to_money(lower_value) > to_money(higher_value):
                    raise PolicyValidationError(f"{field} cannot loosen higher-scope ceiling")

    def _validate_tokens(self, higher: TokenPolicy | None, lower: TokenPolicy | None) -> None:
        if not higher or not lower:
            return
        for field in ("max_tokens", "max_tokens_per_call"):
            higher_value = getattr(higher, field)
            lower_value = getattr(lower, field)
            if higher_value is not None and lower_value is not None:
                if lower_value > higher_value:
                    raise PolicyValidationError(f"{field} cannot loosen higher-scope ceiling")

    def _validate_tools(self, higher: ToolsPolicy | None, lower: ToolsPolicy | None) -> None:
        if not higher or not lower:
            return
        if higher.allowed and lower.allowed:
            for pattern in lower.allowed:
                if not any(_pattern_is_within(pattern, parent) for parent in higher.allowed):
                    raise PolicyValidationError("tools.allowed cannot widen higher-scope allowlist")

    def _validate_approval(
        self, higher: ApprovalPolicy | None, lower: ApprovalPolicy | None
    ) -> None:
        if not higher or not lower:
            return
        if higher.requires_human_approval is True and lower.requires_human_approval is False:
            raise PolicyValidationError("requires_human_approval cannot be disabled")

    def _validate_content_safety(
        self, higher: ContentSafetyPolicy | None, lower: ContentSafetyPolicy | None
    ) -> None:
        if not higher or not lower:
            return
        for field in ("prompt_injection_detection_enabled", "output_sanitizer_enabled"):
            if getattr(higher, field) is True and getattr(lower, field) is False:
                raise PolicyValidationError(f"{field} cannot be disabled")
        if (
            higher.semantic_guard_threshold is not None
            and lower.semantic_guard_threshold is not None
            and lower.semantic_guard_threshold < higher.semantic_guard_threshold
        ):
            raise PolicyValidationError("semantic_guard_threshold cannot be lowered")

    def _merge_budget(
        self, higher: BudgetPolicy | None, lower: BudgetPolicy | None
    ) -> BudgetPolicy | None:
        if not higher:
            return lower
        if not lower:
            return higher
        return BudgetPolicy(
            monthly_spend_cap_usd=_min_money(
                higher.monthly_spend_cap_usd, lower.monthly_spend_cap_usd
            ),
            run_budget_usd=_min_money(higher.run_budget_usd, lower.run_budget_usd),
            service_budget_usd=_min_money(higher.service_budget_usd, lower.service_budget_usd),
        )

    def _merge_tokens(
        self, higher: TokenPolicy | None, lower: TokenPolicy | None
    ) -> TokenPolicy | None:
        if not higher:
            return lower
        if not lower:
            return higher
        return TokenPolicy(
            max_tokens=_min_int(higher.max_tokens, lower.max_tokens),
            max_tokens_per_call=_min_int(higher.max_tokens_per_call, lower.max_tokens_per_call),
        )

    def _merge_tools(
        self, higher: ToolsPolicy | None, lower: ToolsPolicy | None
    ) -> ToolsPolicy | None:
        if not higher:
            return lower
        if not lower:
            return higher
        allowed = lower.allowed if lower.allowed is not None else higher.allowed
        denied = _dedupe([*higher.denied, *lower.denied])
        return ToolsPolicy(allowed=allowed, denied=denied)

    def _merge_approval(
        self, higher: ApprovalPolicy | None, lower: ApprovalPolicy | None
    ) -> ApprovalPolicy | None:
        if not higher:
            return lower
        if not lower:
            return higher
        return ApprovalPolicy(
            requires_human_approval=bool(higher.requires_human_approval)
            or bool(lower.requires_human_approval),
            escalation_rules=_dedupe([*higher.escalation_rules, *lower.escalation_rules]),
        )

    def _merge_content_safety(
        self, higher: ContentSafetyPolicy | None, lower: ContentSafetyPolicy | None
    ) -> ContentSafetyPolicy | None:
        if not higher:
            return lower
        if not lower:
            return higher
        return ContentSafetyPolicy(
            prompt_injection_detection_enabled=bool(higher.prompt_injection_detection_enabled)
            or bool(lower.prompt_injection_detection_enabled),
            output_sanitizer_enabled=bool(higher.output_sanitizer_enabled)
            or bool(lower.output_sanitizer_enabled),
            semantic_guard_threshold=_max_int(
                higher.semantic_guard_threshold, lower.semantic_guard_threshold
            ),
        )


def _min_money(left: Money | None, right: Money | None) -> Money | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(to_money(left), to_money(right))


def _min_int(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _max_int(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _pattern_is_within(child: str, parent: str) -> bool:
    if child == parent:
        return True
    if parent == "*":
        return True
    if "*" not in child and "?" not in child:
        import fnmatch

        return fnmatch.fnmatch(child, parent)
    if parent.endswith("*") and not any(char in parent[:-1] for char in "*?"):
        return child.startswith(parent[:-1])
    return False


class PolicyValidator:
    """Public validation facade for policy documents and monotonic chains."""

    def __init__(self, resolver: PolicyResolver | None = None):
        self.resolver = resolver or PolicyResolver()

    def validate_document(self, document: PolicyDocument) -> PolicyDocument:
        """Validate one policy document's schema and scalar constraints."""
        return policy_from_json(document.to_json_dict())

    def validate_chain(
        self,
        policies: list[PolicyDocument | None],
        *,
        source_policy_ids: list[str] | None = None,
    ) -> EffectivePolicy:
        """Validate a scope chain and return the resulting effective policy."""
        return self.resolver.resolve(policies, source_policy_ids=source_policy_ids)


def monthly_cap_policy(cap_usd: Money) -> PolicyDocument:
    """Build a workspace monthly-cap policy document."""
    return PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd=cap_usd))
