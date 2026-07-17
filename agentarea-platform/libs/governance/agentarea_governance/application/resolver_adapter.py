"""Concrete PolicyResolverPort implementation backed by governance rules.

Resolves the workspace and agent rule layers, compiles each into a typed
:class:`PolicyDocument`, then reuses the unchanged :class:`PolicyResolver`
(monotonic merge + validator). This keeps the runtime ``EffectivePolicy`` — and
the derived ``execution_state`` — byte-for-byte equivalent to the previous
typed-document storage while the source of truth becomes relational rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from agentarea_agents_sdk.tools.code_tools_loader import tools_requiring_confirmation
from agentarea_common.base.repository_factory import RepositoryFactory

from ..domain.policies import (
    EffectivePolicy,
    PolicyDocument,
    PolicyResolver,
)
from ..domain.rules import PolicyRule, PolicySubjectType, rules_to_document
from ..infrastructure.repository import PolicyRuleRepository


class GovernancePolicyResolver:
    """Resolve governance policy through governance repositories.

    Satisfies ``agentarea_common.ports.policy_resolver.PolicyResolverPort``.
    """

    def __init__(
        self,
        repository_factory: RepositoryFactory,
        *,
        tool_confirmation_defaults: Sequence[str] | None = None,
    ):
        self._rule_repository = repository_factory.create_repository(PolicyRuleRepository)
        # Read from the tool registry by default rather than from each caller:
        # the runtime and the policy-preview API build their own resolvers, and a
        # declaration passed to one but not the other would show a verdict the
        # gate does not apply.
        self._tool_confirmation_defaults = list(
            tools_requiring_confirmation()
            if tool_confirmation_defaults is None
            else tool_confirmation_defaults
        )

    async def resolve(
        self,
        *,
        workspace_id: str,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
        task_policy: PolicyDocument | None = None,
    ) -> EffectivePolicy:
        if not workspace_id:
            return EffectivePolicy()

        layers: list[PolicyDocument | None] = []
        source_ids: list[str] = []

        ws_rules = await self._rule_repository.list_rules(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id=workspace_id,
            enabled=True,
        )
        if ws_rules:
            layers.append(rules_to_document(ws_rules))
            source_ids.extend(_rule_ids(ws_rules))

        if agent_id is not None:
            agent_rules = await self._rule_repository.list_rules(
                subject_type=PolicySubjectType.AGENT,
                subject_id=str(agent_id),
                enabled=True,
            )
            if agent_rules:
                layers.append(rules_to_document(agent_rules))
                source_ids.extend(_rule_ids(agent_rules))

        if task_policy is not None:
            layers.append(task_policy)

        return PolicyResolver().resolve(
            layers,
            source_policy_ids=source_ids,
            tool_confirmation_defaults=self._tool_confirmation_defaults,
        )


def _rule_ids(rules: list[PolicyRule]) -> list[str]:
    return [rule.id for rule in rules if rule.id is not None]
