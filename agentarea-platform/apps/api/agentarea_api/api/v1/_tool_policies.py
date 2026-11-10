"""A connection tool's workspace default beside the verdict the workspace's rules give it.

Shared by the Tools page of every kind of connection. A connection kind supplies
the names a run gives each of its tools; the rule this page writes, and the one
tool PDP's verdict over every rule, are the same for all of them.
"""

from typing import Any, Literal

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.tool_authorization import ToolAuthorizationAction, decide_tool_policy
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_governance.application import GovernancePolicyResolver, GovernancePolicyService
from agentarea_governance.domain.policies import PolicyValidationError
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

ToolVerdict = Literal["allow", "approval", "deny"]

_VERDICTS: dict[ToolAuthorizationAction, ToolVerdict] = {
    ToolAuthorizationAction.ALLOW: "allow",
    ToolAuthorizationAction.REQUIRE_APPROVAL: "approval",
    ToolAuthorizationAction.DENY: "deny",
}
_STRICTNESS: dict[ToolVerdict, int] = {"allow": 0, "approval": 1, "deny": 2}


class MCPInstanceToolPolicy(BaseModel):
    """One tool of a connection: its workspace default and the workspace's verdict on it."""

    name: str
    # The workspace rule naming exactly this tool of this connection; none is allow.
    # An approval rule that names its approvers is not a default: it was set elsewhere.
    default: ToolVerdict
    # What all of the workspace's rules make of the tool, as the tool PDP decides it.
    effective: ToolVerdict
    # The PDP's reason, when the effective verdict is stricter than the default.
    reason: str | None = None


class MCPInstanceToolPolicies(BaseModel):
    tools: list[MCPInstanceToolPolicy]


def _default_verdict(rules: list[PolicyRule], target: str) -> ToolVerdict:
    effects = {
        rule.effect
        for rule in rules
        if rule.target == target
        and not rule.condition
        and not (rule.effect == PolicyEffect.APPROVAL and (rule.params or {}).get("approvers"))
    }
    if PolicyEffect.DENY in effects:
        return "deny"
    if PolicyEffect.APPROVAL in effects:
        return "approval"
    return "allow"


def tool_policy(
    name: str,
    *,
    rule_target: str,
    pdp_target: str,
    restricting_aliases: tuple[str, ...],
    workspace_rules: list[PolicyRule],
    workspace_policy: dict[str, Any],
) -> MCPInstanceToolPolicy:
    """One tool's default, the rule on ``rule_target``, beside the PDP's verdict.

    ``pdp_target`` is the name that may allow the tool; ``restricting_aliases``
    are the names that may only deny it or hold it for approval.
    """
    default = _default_verdict(workspace_rules, rule_target)
    decision = decide_tool_policy(
        workspace_policy, pdp_target, restricting_aliases=restricting_aliases
    )
    effective = _VERDICTS[decision.action]
    stricter = _STRICTNESS[effective] > _STRICTNESS[default]
    return MCPInstanceToolPolicy(
        name=name,
        default=default,
        effective=effective,
        reason=decision.reason if stricter else None,
    )


async def workspace_tool_policy(
    session: AsyncSession, user_context: UserContext
) -> tuple[list[PolicyRule], dict[str, Any]]:
    """The workspace's enabled rules and its resolved policy layer, as the verdicts read them."""
    repository_factory = RepositoryFactory(session, user_context)
    workspace_rules = await GovernancePolicyService(repository_factory).list_rules(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id=user_context.workspace_id,
        enabled=True,
    )
    try:
        workspace_policy = await GovernancePolicyResolver(repository_factory).resolve(
            workspace_id=user_context.workspace_id
        )
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workspace_rules, workspace_policy.to_json_dict()
