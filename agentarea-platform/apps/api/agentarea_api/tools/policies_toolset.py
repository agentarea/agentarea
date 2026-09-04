"""PoliciesToolset — read and write the workspace's governance rules.

Writes go through ``assert_enforceable`` for the same reason the REST router
does: the rule compiler debug-skips rules it cannot enforce, so accepting one
here would hand back a success for a rule that never fires.

Rule bodies mirror ``PolicyRuleCreateRequest``/``PolicyRuleUpdateRequest`` in
``api/v1/policies.py``; the flat kwargs below are the MCP wire shape for them.
"""

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_governance.application import GovernancePolicyResolver, GovernancePolicyService
from agentarea_governance.domain.policies import PolicyValidationError, effective_policy_from_json
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    assert_enforceable,
)
from agentarea_tasks.infrastructure.repository import TaskRepository

from ..api.v1.policies import PolicyRuleCreateRequest, PolicyRuleUpdateRequest
from .base import platform_context, platform_read_context

RULE_NOT_FOUND = json.dumps({"error": "Policy rule not found"})


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

    @tool_method(effect="read")
    async def list(
        self,
        subject_type: str | None = None,
        subject_id: str | None = None,
        effect: str | None = None,
        target: str | None = None,
        enabled: bool | None = None,
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

    @tool_method(effect="read")
    async def get(self, rule_id: str) -> str:
        """Read one policy rule."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            rule = await service.get_rule(rule_id=UUID(rule_id))
            if rule is None:
                return RULE_NOT_FOUND
            return json.dumps(_rule_json(rule), default=str)

    @tool_method(effect="privileged")
    async def create(
        self,
        subject_type: str,
        subject_id: str,
        target: str,
        effect: str,
        params: dict[str, Any] | None = None,
        condition: str | None = None,
        enabled: bool = True,
        priority: int = 0,
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
            return json.dumps({"error": str(exc)})

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            created = await service.create_rule(rule=rule, subject_id=payload.subject_id)
            return json.dumps(_rule_json(created), default=str)

    @tool_method(effect="privileged")
    async def update(
        self,
        rule_id: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
        target: str | None = None,
        effect: str | None = None,
        params: dict[str, Any] | None = None,
        condition: str | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
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
            return json.dumps({"error": str(exc)})

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            existing = await service.get_rule(rule_id=UUID(rule_id))
            if existing is None:
                return RULE_NOT_FOUND
            try:
                assert_enforceable(existing.model_copy(update=fields))
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            updated = await service.update_rule(rule_id=UUID(rule_id), **fields)
            if updated is None:
                return RULE_NOT_FOUND
            return json.dumps(_rule_json(updated), default=str)

    @tool_method(effect="destructive")
    async def delete(self, rule_id: str) -> str:
        """Delete a policy rule."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            deleted = await service.delete_rule(rule_id=UUID(rule_id))
            if not deleted:
                return RULE_NOT_FOUND
            return json.dumps({"deleted": True})

    @tool_method(effect="read")
    async def preview_effective_policy(self, agent_id: str | None = None) -> str:
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
                return json.dumps({"error": str(exc)})
            return json.dumps(effective.model_dump(), default=str)

    @tool_method(effect="read")
    async def get_run_policy(self, run_id: str) -> str:
        """Read the policy snapshot a run was dispatched under."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            task_repository = repo_factory.create_repository(TaskRepository)
            task = await task_repository.get_task(UUID(run_id))
            snapshot = (task.metadata or {}).get("governance_snapshot") if task else None
            effective_policy = (
                snapshot.get("effective_policy") if isinstance(snapshot, dict) else None
            )
            if not isinstance(effective_policy, dict):
                return json.dumps({"error": "Run policy snapshot not found"})
            return json.dumps(
                effective_policy_from_json(effective_policy).model_dump(), default=str
            )
