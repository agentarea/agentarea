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
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from agentarea_common.money import to_money
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .policies import (
    ApprovalPolicy,
    BudgetPolicy,
    ContentSafetyPolicy,
    ExecutionLimitsPolicy,
    PolicyDocument,
    TokenPolicy,
    ToolsPolicy,
    parse_subject,
)

logger = logging.getLogger(__name__)


class PolicyEffect(StrEnum):
    """What a rule does when it applies."""

    ALLOW = "allow"
    DENY = "deny"
    CAP = "cap"
    APPROVAL = "approval"
    SAFETY = "safety"
    # Container-level egress allowlist for an MCP (``target=mcp:<id>``). Core
    # stores and round-trips these rows but does NOT enforce the container network
    # boundary — that is the enterprise EgressEnforcer. They intentionally do not
    # compile into the runtime PolicyDocument; read them with
    # egress_allowlist_from_rules(). Host patterns live in params["allowed_hosts"].
    EGRESS = "egress"


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
        "execution",
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


class SpendCapParams(BaseModel):
    """``params`` for a ``cap`` on ``spend`` (per calendar month or per run)."""

    model_config = ConfigDict(extra="forbid")

    amount_usd: Decimal = Field(ge=0)
    period: Literal["month", "run"] = "month"


class ServiceCapParams(BaseModel):
    """``params`` for a ``cap`` on ``service`` spend."""

    model_config = ConfigDict(extra="forbid")

    amount_usd: Decimal = Field(gt=0)


class TokenCapParams(BaseModel):
    """``params`` for a ``cap`` on ``tokens``; at least one ceiling is required."""

    model_config = ConfigDict(extra="forbid")

    max_tokens: int | None = Field(default=None, gt=0)
    max_tokens_per_call: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _require_one(self) -> TokenCapParams:
        if self.max_tokens is None and self.max_tokens_per_call is None:
            raise ValueError("token cap requires 'max_tokens' or 'max_tokens_per_call'")
        return self


class ExecutionCapParams(BaseModel):
    """``params`` for a ``cap`` on ``execution``; at least one ceiling is required."""

    model_config = ConfigDict(extra="forbid")

    max_model_turns: int | None = Field(default=None, gt=0)
    max_tool_calls_per_turn: int | None = Field(default=None, gt=0)
    max_tool_calls_total: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _require_one(self) -> ExecutionCapParams:
        if (
            self.max_model_turns is None
            and self.max_tool_calls_per_turn is None
            and self.max_tool_calls_total is None
        ):
            raise ValueError(
                "execution cap requires 'max_model_turns', 'max_tool_calls_per_turn', "
                "or 'max_tool_calls_total'"
            )
        return self


class ApprovalParams(BaseModel):
    """``params`` for an ``approval`` rule; approvers are Keto-style subject refs."""

    model_config = ConfigDict(extra="forbid")

    approvers: list[str] = Field(default_factory=list)

    @field_validator("approvers")
    @classmethod
    def _validate_refs(cls, value: list[str]) -> list[str]:
        for ref in value:
            parse_subject(ref)  # raises ValueError on a non subject-ref (e.g. a raw id)
        return value


class SafetyParams(BaseModel):
    """``params`` for a ``safety`` rule on ``content``; at least one toggle required."""

    model_config = ConfigDict(extra="forbid")

    prompt_injection: bool | None = None
    output_sanitizer: bool | None = None

    @model_validator(mode="after")
    def _require_one(self) -> SafetyParams:
        if self.prompt_injection is None and self.output_sanitizer is None:
            raise ValueError("safety on content requires 'prompt_injection' or 'output_sanitizer'")
        return self


# Which typed param model validates a cap for each cap target kind.
_CAP_PARAM_MODEL: dict[str, type[BaseModel]] = {
    "spend": SpendCapParams,
    "service": ServiceCapParams,
    "tokens": TokenCapParams,
    "execution": ExecutionCapParams,
}


def _validate_params(rule: PolicyRule, model: type[BaseModel]) -> None:
    """Validate ``rule.params`` through a typed model at the write boundary.

    Pydantic's ``ValidationError`` does not subclass ``ValueError`` in v2, so the
    write API's ``except ValueError`` would miss it; translate it into a compact,
    caller-facing ``ValueError`` instead of surfacing the multi-line pydantic dump.
    """
    try:
        model.model_validate(rule.params or {})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc']) or 'params'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ValueError(
            f"invalid params for {rule.effect.value} on {rule.target!r}: {problems}"
        ) from exc


def assert_enforceable(rule: PolicyRule) -> None:
    """Reject a rule the engine would silently ignore at runtime.

    The compiler debug-skips unenforceable rules, so without this guard the write
    API returns 201 for rules that never take effect (fail-open). Fail loudly at
    the write boundary instead: the effect/target selector is checked structurally,
    then ``params`` is validated through the matching typed model above. This runs
    only on create/update — never when loading existing rows from the database.

    Raises:
        ValueError: with a caller-facing reason when the rule cannot be enforced.
    """
    if rule.subject_type == PolicySubjectType.GROUP:
        raise ValueError(
            "group subjects are not resolved yet (issue #198); bind the rule to a "
            "workspace, agent, or user"
        )
    if rule.condition is not None:
        raise ValueError("conditions (CEL) are not evaluated yet; omit 'condition'")

    kind, value = parse_target(rule.target)  # raises ValueError on an unknown kind
    effect = rule.effect

    if effect == PolicyEffect.CAP:
        model = _CAP_PARAM_MODEL.get(kind)
        if model is None:
            raise ValueError(
                f"cap on {rule.target!r} is not enforceable; caps apply to "
                "spend, service, tokens, or execution"
            )
        _validate_params(rule, model)
        return

    if effect in (PolicyEffect.DENY, PolicyEffect.ALLOW):
        if kind != "tool":
            raise ValueError(
                f"{effect.value} is only enforceable on a tool target (tool:<name>), "
                f"not {rule.target!r}"
            )
        if value in (None, "*"):
            raise ValueError(
                f"{effect.value} requires a specific tool (tool:<name>), not a wildcard "
                f"{rule.target!r}"
            )
        return

    if effect == PolicyEffect.APPROVAL:
        if not (kind == "all" or (kind == "tool" and (value == "*" or value))):
            raise ValueError(
                f"approval is enforceable on '*' (all tools) or tool:<name>, not {rule.target!r}"
            )
        _validate_params(rule, ApprovalParams)
        return

    if effect == PolicyEffect.SAFETY:
        if kind != "content":
            raise ValueError(f"safety is only enforceable on a content target, not {rule.target!r}")
        _validate_params(rule, SafetyParams)
        return

    if effect == PolicyEffect.EGRESS:
        # Accepted as opaque data — core neither validates nor enforces egress.
        # Enforcement is the enterprise EgressEnforcer at the container network
        # boundary; core only stores and round-trips the rows for it to consume.
        return

    raise ValueError(f"effect {effect.value!r} on {rule.target!r} is not enforceable")


class _DocumentAccumulator:
    """Mutable scratch space that the compiler folds rules into."""

    def __init__(self) -> None:
        self.budget: dict[str, Any] = {}
        self.tokens: dict[str, Any] = {}
        self.execution: dict[str, Any] = {}
        self.tools_allowed: list[str] = []
        self.tools_denied: list[str] = []
        self.approval_required: bool = False
        self.escalation_rules: list[str] = []
        self.approvers: list[str] = []
        self.approvers_by_tool: dict[str, list[str]] = {}
        self.content_safety: dict[str, Any] = {}

    def to_document(self) -> PolicyDocument:
        budget = BudgetPolicy(**self.budget) if self.budget else None
        tokens = TokenPolicy(**self.tokens) if self.tokens else None
        execution = ExecutionLimitsPolicy(**self.execution) if self.execution else None

        tools: ToolsPolicy | None = None
        if self.tools_allowed or self.tools_denied:
            tools = ToolsPolicy(
                allowed=_dedupe(self.tools_allowed) or None,
                denied=_dedupe(self.tools_denied),
            )

        approval: ApprovalPolicy | None = None
        if (
            self.approval_required
            or self.escalation_rules
            or self.approvers
            or self.approvers_by_tool
        ):
            approval = ApprovalPolicy(
                requires_human_approval=True if self.approval_required else None,
                escalation_rules=_dedupe(self.escalation_rules),
                approvers=_dedupe(self.approvers),
                approvers_by_tool={
                    tool: _dedupe(refs) for tool, refs in self.approvers_by_tool.items()
                },
            )

        content_safety = ContentSafetyPolicy(**self.content_safety) if self.content_safety else None

        return PolicyDocument(
            budget=budget,
            tokens=tokens,
            execution=execution,
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

    if rule.effect == PolicyEffect.EGRESS:
        # Enforced at the container network layer (enterprise EgressEnforcer), not
        # by the in-process guards — never compiles into the runtime document.
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

    if kind == "execution":
        for field in (
            "max_model_turns",
            "max_tool_calls_per_turn",
            "max_tool_calls_total",
        ):
            if field in params:
                acc.execution[field] = params[field]
        return

    logger.debug("skipping cap rule %s: unsupported cap target %r", rule.id, rule.target)


def _apply_approval(
    acc: _DocumentAccumulator,
    rule: PolicyRule,
    kind: str,
    value: str | None,
    params: dict[str, Any],
) -> None:
    approvers = params.get("approvers") or []

    if kind == "all" or (kind == "tool" and value == "*"):
        acc.approval_required = True
        # Global approval: approvers apply to every tool, so they stay flat.
        acc.approvers.extend(approvers)
    elif kind == "tool" and value:
        # An approval rule that targets a tool keeps approval-on-tool working:
        # helpers.policy_requires_approval checks escalation_rules membership.
        # Approvers stay keyed by that tool so distinct tools keep distinct
        # signoff lists instead of flattening into one shared pool.
        acc.escalation_rules.append(value)
        if approvers:
            acc.approvers_by_tool.setdefault(value, []).extend(approvers)
    else:
        logger.debug("skipping approval rule %s: unsupported target %r", rule.id, rule.target)


def _apply_safety(acc: _DocumentAccumulator, params: dict[str, Any]) -> None:
    if "prompt_injection" in params:
        acc.content_safety["prompt_injection_detection_enabled"] = bool(params["prompt_injection"])
    if "output_sanitizer" in params:
        acc.content_safety["output_sanitizer_enabled"] = bool(params["output_sanitizer"])


def egress_allowlist_from_rules(rules: list[PolicyRule]) -> dict[str, list[str]]:
    """Collect enabled egress allowlists keyed by target selector.

    Returns e.g. ``{"mcp:<id>": ["*.github.com", "api.github.com"]}``. Host
    patterns come from ``params["allowed_hosts"]``. This is the seam the
    enterprise ``EgressEnforcer`` consumes: core owns the data, enterprise owns
    the container-network enforcement. A target present with an empty list means
    default-deny (declared, nothing allowed).
    """
    result: dict[str, list[str]] = {}
    for rule in rules:
        if not rule.enabled or rule.effect != PolicyEffect.EGRESS:
            continue
        hosts = (rule.params or {}).get("allowed_hosts", [])
        if not isinstance(hosts, list):
            logger.debug("skipping egress rule %s: allowed_hosts is not a list", rule.id)
            continue
        result.setdefault(rule.target, []).extend(str(h) for h in hosts)
    return {target: _dedupe(hosts) for target, hosts in result.items()}


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
