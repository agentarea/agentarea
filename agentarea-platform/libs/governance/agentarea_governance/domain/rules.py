"""Unified relational policy rules — the governance source of truth.

A single ``PolicyRule`` row expresses one governance intent (allow/deny a tool,
cap spend, require approval, enable a safety filter) for one subject. Rules of a
single subject layer compile into a typed :class:`PolicyDocument` so the existing
:class:`PolicyResolver` (monotonic merge + validator) keeps producing the exact
same ``EffectivePolicy`` — and thus the same ``execution_state``. The runtime
contract is unchanged; only the storage shape changed.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from agentarea_common.money import to_money
from pydantic import BaseModel, ConfigDict, Field

from .policies import (
    ApprovalPolicy,
    BudgetPolicy,
    ContentSafetyPolicy,
    PolicyDocument,
    TokenPolicy,
    ToolsPolicy,
)

logger = logging.getLogger(__name__)


class PolicyEffect(StrEnum):
    """What a rule does when it applies."""

    ALLOW = "allow"
    DENY = "deny"
    CAP = "cap"
    APPROVAL = "approval"
    SAFETY = "safety"


class PolicySubjectType(StrEnum):
    """The kind of subject a rule binds to."""

    WORKSPACE = "workspace"
    AGENT = "agent"
    USER = "user"
    GROUP = "group"


class PolicyRule(BaseModel):
    """One unified governance rule for a single subject."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    enabled: bool = True
    priority: int = 0
    subject_type: PolicySubjectType
    subject_id: str
    target: str
    effect: PolicyEffect
    params: dict[str, Any] = Field(default_factory=dict)
    condition: str | None = None


# Selector kinds the compiler understands.
_TARGET_KINDS = frozenset(
    {
        "tool",
        "mcp",
        "model",
        "skill",
        "collection",
        "spend",
        "service",
        "tokens",
        "content",
        "all",
    }
)


def parse_target(selector: str) -> tuple[str, str | None]:
    """Parse a target selector into ``(kind, value)``.

    Examples::

        "tool:send_email" -> ("tool", "send_email")
        "tool:*"          -> ("tool", "*")
        "spend"           -> ("spend", None)
        "*"               -> ("all", None)

    Raises:
        ValueError: when the selector is empty, malformed, or names an unknown
            kind. Garbage in must fail loudly rather than silently no-op.
    """
    if not isinstance(selector, str) or not selector:
        raise ValueError(f"invalid target selector {selector!r}: must be a non-empty string")

    if selector == "*":
        return "all", None

    if ":" not in selector:
        kind = selector
        value: str | None = None
    else:
        kind, raw_value = selector.split(":", 1)
        if not kind or not raw_value:
            raise ValueError(f"invalid target selector {selector!r}: empty component")
        value = raw_value

    if kind not in _TARGET_KINDS:
        raise ValueError(f"invalid target selector {selector!r}: unknown kind {kind!r}")

    return kind, value


class _DocumentAccumulator:
    """Mutable scratch space that the compiler folds rules into."""

    def __init__(self) -> None:
        self.budget: dict[str, Any] = {}
        self.tokens: dict[str, Any] = {}
        self.tools_allowed: list[str] = []
        self.tools_denied: list[str] = []
        self.approval_required: bool = False
        self.escalation_rules: list[str] = []
        self.approvers: list[str] = []
        self.content_safety: dict[str, Any] = {}

    def to_document(self) -> PolicyDocument:
        budget = BudgetPolicy(**self.budget) if self.budget else None
        tokens = TokenPolicy(**self.tokens) if self.tokens else None

        tools: ToolsPolicy | None = None
        if self.tools_allowed or self.tools_denied:
            tools = ToolsPolicy(
                allowed=_dedupe(self.tools_allowed) or None,
                denied=_dedupe(self.tools_denied),
            )

        approval: ApprovalPolicy | None = None
        if self.approval_required or self.escalation_rules or self.approvers:
            approval = ApprovalPolicy(
                requires_human_approval=True if self.approval_required else None,
                escalation_rules=_dedupe(self.escalation_rules),
                approvers=_dedupe(self.approvers),
            )

        content_safety = ContentSafetyPolicy(**self.content_safety) if self.content_safety else None

        return PolicyDocument(
            budget=budget,
            tokens=tokens,
            tools=tools,
            approval=approval,
            content_safety=content_safety,
        )


def rules_to_document(rules: list[PolicyRule]) -> PolicyDocument:
    """Compile one subject layer's rules into a typed :class:`PolicyDocument`.

    Disabled rules are ignored. Rules whose effect/target the compiler does not
    recognize are skipped (logged at debug) — they still exist as rows for the
    UI's "Custom" surface but never reach the runtime document.
    """
    acc = _DocumentAccumulator()

    for rule in rules:
        if not rule.enabled:
            continue
        try:
            kind, value = parse_target(rule.target)
        except ValueError:
            logger.debug("skipping rule %s: unparseable target %r", rule.id, rule.target)
            continue
        _apply_rule(acc, rule, kind, value)

    return acc.to_document()


def _apply_rule(
    acc: _DocumentAccumulator,
    rule: PolicyRule,
    kind: str,
    value: str | None,
) -> None:
    params = rule.params or {}

    if rule.effect == PolicyEffect.CAP:
        _apply_cap(acc, rule, kind, params)
        return

    if rule.effect == PolicyEffect.DENY and kind == "tool":
        if value in (None, "*"):
            logger.debug("skipping deny rule %s: wildcard tool target", rule.id)
            return
        acc.tools_denied.append(value)
        return

    if rule.effect == PolicyEffect.ALLOW and kind == "tool":
        if value in (None, "*"):
            logger.debug("skipping allow rule %s: wildcard tool target", rule.id)
            return
        acc.tools_allowed.append(value)
        return

    if rule.effect == PolicyEffect.APPROVAL:
        _apply_approval(acc, rule, kind, value, params)
        return

    if rule.effect == PolicyEffect.SAFETY and kind == "content":
        _apply_safety(acc, params)
        return

    logger.debug(
        "skipping rule %s: unsupported effect/target (%s/%s)",
        rule.id,
        rule.effect,
        rule.target,
    )


def _apply_cap(
    acc: _DocumentAccumulator,
    rule: PolicyRule,
    kind: str,
    params: dict[str, Any],
) -> None:
    if kind == "spend":
        amount = params.get("amount_usd")
        if amount is None:
            logger.debug("skipping cap rule %s: spend cap missing amount_usd", rule.id)
            return
        period = params.get("period", "month")
        if period == "month":
            acc.budget["monthly_spend_cap_usd"] = to_money(amount)
        elif period == "run":
            acc.budget["run_budget_usd"] = to_money(amount)
        else:
            logger.debug("skipping cap rule %s: unknown spend period %r", rule.id, period)
        return

    if kind == "service":
        amount = params.get("amount_usd")
        if amount is None:
            logger.debug("skipping cap rule %s: service cap missing amount_usd", rule.id)
            return
        acc.budget["service_budget_usd"] = to_money(amount)
        return

    if kind == "tokens":
        if "max_tokens" in params:
            acc.tokens["max_tokens"] = params["max_tokens"]
        if "max_tokens_per_call" in params:
            acc.tokens["max_tokens_per_call"] = params["max_tokens_per_call"]
        return

    logger.debug("skipping cap rule %s: unsupported cap target %r", rule.id, rule.target)


def _apply_approval(
    acc: _DocumentAccumulator,
    rule: PolicyRule,
    kind: str,
    value: str | None,
    params: dict[str, Any],
) -> None:
    if kind == "all" or (kind == "tool" and value == "*"):
        acc.approval_required = True
    elif kind == "tool" and value:
        # An approval rule that targets a tool keeps approval-on-tool working:
        # helpers.policy_requires_approval checks escalation_rules membership.
        acc.escalation_rules.append(value)
    else:
        logger.debug("skipping approval rule %s: unsupported target %r", rule.id, rule.target)

    approvers = params.get("approvers")
    if approvers:
        acc.approvers.extend(approvers)


def _apply_safety(acc: _DocumentAccumulator, params: dict[str, Any]) -> None:
    if "prompt_injection" in params:
        acc.content_safety["prompt_injection_detection_enabled"] = bool(params["prompt_injection"])
    if "output_sanitizer" in params:
        acc.content_safety["output_sanitizer_enabled"] = bool(params["output_sanitizer"])


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
