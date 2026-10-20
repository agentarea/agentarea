"""PoliciesToolset — read and write the workspace's governance rules.

Writes go through ``assert_enforceable`` for the same reason the REST router
does: the rule compiler debug-skips rules it cannot enforce, so accepting one
here would hand back a success for a rule that never fires.

Rule bodies mirror ``PolicyRuleCreateRequest``/``PolicyRuleUpdateRequest`` in
``api/v1/policies.py``; the flat kwargs below are the MCP wire shape for them.
"""

import json
from typing import Annotated, Any
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import requires_workspace_admin, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_governance.application import GovernancePolicyResolver, GovernancePolicyService
from agentarea_governance.domain.policies import (
    EffectivePolicy,
    PolicyValidationError,
    effective_policy_from_json,
)
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    assert_enforceable,
)
from agentarea_tasks.infrastructure.repository import TaskRepository
from pydantic import BaseModel, Field

from ..api.v1.policies import (
    PolicyRuleCreateRequest,
    PolicyRuleResponse,
    PolicyRuleUpdateRequest,
)
from .base import platform_context, platform_read_context

RULE_NOT_FOUND = "Policy rule not found"

_RULE_ID = "Policy rule id (UUID), from `policies_list` or `policies_create`."
_SUBJECT_TYPE = "Kind of subject the rule binds to; group is not resolved yet and is rejected."
_SUBJECT_ID = "Id of the subject: the workspace id, an agent id from `agents_list`, or a user id."
_TARGET = (
    "Selector the rule applies to, `<kind>` or `<kind>:<value>`: kind is one of tool, mcp, "
    "model, skill, collection, spend, service, tokens, execution, content; e.g. "
    "`tool:send_email`, `tool:*`, `mcp:<instance id>`, `spend`, or `*` for everything."
)
_EFFECT = (
    "What the rule does: allow, deny, cap (params hold the ceiling), approval (params may "
    "list approvers), safety, or egress (an MCP's allowed hosts)."
)
_PARAMS = (
    'Effect-specific settings as a JSON object, e.g. {"amount_usd": 10, "period": "month"} '
    'for a cap on spend, {"max_tokens": 50000} for a cap on tokens, '
    '{"approvers": ["user:<id>"]} for approval.'
)
_CONDITION = "CEL condition; not evaluated yet, so a rule that sets one is rejected."
_PRIORITY = "Ordering among rules for the same subject and target, a 32-bit signed integer."


class PolicyRuleDeletedOutput(BaseModel):
    deleted: bool = Field(description="True once the rule is gone.")


def _build_service(repo_factory) -> GovernancePolicyService:
    return GovernancePolicyService(repo_factory)


def _build_resolver(repo_factory) -> GovernancePolicyResolver:
    return GovernancePolicyResolver(repo_factory)


def _rule_json(rule: PolicyRule) -> dict[str, Any]:
    return {
        "id": rule.id or "",
        "enabled": rule.enabled,
        "priority": rule.priority,
        "subject_type": rule.subject_type,
        "subject_id": rule.subject_id,
        "target": rule.target,
        "effect": rule.effect,
        "params": rule.params,
        "condition": rule.condition,
    }


@toolset(
    namespace="agentarea/policies",
    display_name="Governance Policies",
    description="List, inspect, and write the workspace's governance policy rules.",
    category="platform",
    plane="govern",
)
class PoliciesToolset(Toolset):
    """Read and write governance rules, and preview the policy they resolve to."""

    open_world = False

    @tool_method(display_name="List policy rules", effect="read", output=list[PolicyRuleResponse])
    @requires_workspace_admin()
    async def list(
        self,
        subject_type: Annotated[
            PolicySubjectType | None, Field(description="Only rules bound to this kind of subject.")
        ] = None,
        subject_id: Annotated[
            str | None, Field(description="Only rules bound to this subject id.")
        ] = None,
        effect: Annotated[
            PolicyEffect | None, Field(description="Only rules with this effect.")
        ] = None,
        target: Annotated[
            str | None,
            Field(description="Only rules with exactly this target selector, e.g. `tool:shell`."),
        ] = None,
        enabled: Annotated[
            bool | None, Field(description="Only enabled (true) or disabled (false) rules.")
        ] = None,
    ) -> str:
        """List policy rules in the workspace, optionally filtered."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            rules = await service.list_rules(
                subject_type=PolicySubjectType(subject_type) if subject_type else None,
                subject_id=subject_id,
                effect=PolicyEffect(effect) if effect else None,
                target=target,
                enabled=enabled,
            )
            return json.dumps([_rule_json(r) for r in rules], default=str)

    @tool_method(display_name="Get policy rule", effect="read", output=PolicyRuleResponse)
    @requires_workspace_admin()
    async def get(self, rule_id: Annotated[str, Field(description=_RULE_ID)]) -> str:
        """Read one policy rule."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            rule = await service.get_rule(rule_id=UUID(rule_id))
            if rule is None:
                raise ToolError(RULE_NOT_FOUND)
            return json.dumps(_rule_json(rule), default=str)

    @tool_method(display_name="Create policy rule", effect="privileged", output=PolicyRuleResponse)
    @requires_workspace_admin()
    async def create(
        self,
        subject_type: Annotated[PolicySubjectType, Field(description=_SUBJECT_TYPE)],
        subject_id: Annotated[str, Field(description=_SUBJECT_ID)],
        target: Annotated[str, Field(description=_TARGET)],
        effect: Annotated[PolicyEffect, Field(description=_EFFECT)],
        params: Annotated[
            dict[str, Any] | None, Field(description=f"{_PARAMS} Omit for none.")
        ] = None,
        condition: Annotated[str | None, Field(description=_CONDITION)] = None,
        enabled: Annotated[bool, Field(description="Whether the rule takes effect.")] = True,
        priority: Annotated[int, Field(description=_PRIORITY)] = 0,
    ) -> str:
        """Create a policy rule. Rejects rules the engine could not enforce."""
        try:
            payload = PolicyRuleCreateRequest.model_validate(
                {
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "target": target,
                    "effect": effect,
                    "params": params or {},
                    "condition": condition,
                    "enabled": enabled,
                    "priority": priority,
                }
            )
            rule = PolicyRule(
                subject_type=payload.subject_type,
                subject_id=payload.subject_id,
                target=payload.target,
                effect=payload.effect,
                params=payload.params,
                condition=payload.condition,
                enabled=payload.enabled,
                priority=payload.priority,
            )
            assert_enforceable(rule)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            created = await service.create_rule(rule=rule)
            return json.dumps(_rule_json(created), default=str)

    @tool_method(
        display_name="Update policy rule",
        effect="privileged",
        idempotent=True,
        output=PolicyRuleResponse,
    )
    @requires_workspace_admin()
    async def update(
        self,
        rule_id: Annotated[str, Field(description=_RULE_ID)],
        subject_type: Annotated[
            PolicySubjectType | None, Field(description=f"{_SUBJECT_TYPE} Omit to keep it.")
        ] = None,
        subject_id: Annotated[
            str | None, Field(description=f"{_SUBJECT_ID} Omit to keep it.")
        ] = None,
        target: Annotated[str | None, Field(description=f"{_TARGET} Omit to keep it.")] = None,
        effect: Annotated[
            PolicyEffect | None, Field(description=f"{_EFFECT} Omit to keep it.")
        ] = None,
        params: Annotated[
            dict[str, Any] | None,
            Field(description=f"{_PARAMS} Replaces the whole object; omit to keep it."),
        ] = None,
        condition: Annotated[str | None, Field(description=_CONDITION)] = None,
        enabled: Annotated[
            bool | None,
            Field(description="Turn the rule on (true) or off (false); omit to keep it."),
        ] = None,
        priority: Annotated[int | None, Field(description=f"{_PRIORITY} Omit to keep it.")] = None,
    ) -> str:
        """Update a policy rule. Only fields explicitly set are written."""
        patch: dict[str, Any] = {
            key: value
            for key, value in {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "target": target,
                "effect": effect,
                "params": params,
                "condition": condition,
                "enabled": enabled,
                "priority": priority,
            }.items()
            if value is not None
        }
        try:
            fields = PolicyRuleUpdateRequest.model_validate(patch).model_dump(exclude_unset=True)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            existing = await service.get_rule(rule_id=UUID(rule_id))
            if existing is None:
                raise ToolError(RULE_NOT_FOUND)
            try:
                assert_enforceable(existing.model_copy(update=fields))
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            updated = await service.update_rule(rule_id=UUID(rule_id), **fields)
            if updated is None:
                raise ToolError(RULE_NOT_FOUND)
            return json.dumps(_rule_json(updated), default=str)

    @tool_method(
        display_name="Delete policy rule",
        effect="destructive",
        idempotent=True,
        output=PolicyRuleDeletedOutput,
    )
    @requires_workspace_admin()
    async def delete(self, rule_id: Annotated[str, Field(description=_RULE_ID)]) -> str:
        """Delete a policy rule."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            deleted = await service.delete_rule(rule_id=UUID(rule_id))
            if not deleted:
                raise ToolError(RULE_NOT_FOUND)
            return json.dumps({"deleted": True})

    @tool_method(display_name="Preview effective policy", effect="read", output=EffectivePolicy)
    @unrestricted(
        "the ceiling a run would get, as POST /v1/governance/effective-policy/preview shows any member"
    )
    async def preview_effective_policy(
        self,
        agent_id: Annotated[
            str | None,
            Field(
                description="Agent id (UUID) from `agents_list` whose rules are layered on the "
                "workspace's; omit for the workspace ceiling alone."
            ),
        ] = None,
    ) -> str:
        """Resolve the policy ceiling that would apply, without persisting it."""
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            resolver = _build_resolver(repo_factory)
            try:
                effective = await resolver.resolve(
                    workspace_id=user_ctx.workspace_id,
                    agent_id=UUID(agent_id) if agent_id else None,
                    task_policy=None,
                )
            except PolicyValidationError as exc:
                raise ToolError(str(exc)) from exc
            return json.dumps(effective.model_dump(), default=str)

    @tool_method(display_name="Get run policy", effect="read", output=EffectivePolicy)
    @unrestricted(
        "the snapshot a run ran under, as GET /v1/governance/task-policy-snapshots/{id} returns it"
    )
    async def get_run_policy(
        self,
        run_id: Annotated[
            str, Field(description="Run id (UUID), from `runs_list` or `runs_start`.")
        ],
    ) -> str:
        """Read the policy snapshot a run was dispatched under."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            task_repository = repo_factory.create_repository(TaskRepository)
            task = await task_repository.get_task(UUID(run_id))
            snapshot = (task.metadata or {}).get("governance_snapshot") if task else None
            effective_policy = (
                snapshot.get("effective_policy") if isinstance(snapshot, dict) else None
            )
            if not isinstance(effective_policy, dict):
                raise ToolError("Run policy snapshot not found")
            return json.dumps(
                effective_policy_from_json(effective_policy).model_dump(), default=str
            )
