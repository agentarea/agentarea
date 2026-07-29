"""Translate the agent editor's per-tool "requires approval" toggle into rules.

The toggle used to live in the agent's ``tools`` JSON, where nothing enforced
it. Approval is a governance decision, so it belongs in the policy engine: each
ticked tool becomes an agent-scoped ``PolicyRule(target="tool:<name>",
effect=APPROVAL)``, which the resolver already folds into the snapshot the
workflow gate reads. The toggle's state is the source of truth, so unticking
removes the row rather than disabling it.

The one subtlety is the name. Policy judges the LLM-facing name: a code toolset
collapses its namespace (``agentarea/shell`` -> ``shell``), while an MCP tool
keeps the raw name it advertises, which is exactly the ``allowed_tools`` entry.

This lives in the agents lib (not the API app) so every agent-creation path —
the router, bundle install, workspace import, and catalog fork — reconciles
approval rules through the one home: ``AgentService``.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession


def _llm_facing_name(tool_name: str) -> str:
    """Collapse a code toolset namespace to the name the model actually calls."""
    return tool_name.rsplit("/", 1)[-1]


def approval_targets_from_tools(tools: list[dict]) -> set[str]:
    """Rule targets for every tool the config marks as requiring approval."""
    targets: set[str] = set()
    for tool in tools:
        settings = tool.get("settings") or {}
        if tool.get("type") == "mcp":
            for perm in settings.get("allowed_tools") or []:
                if isinstance(perm, dict) and perm.get("requires_user_confirmation"):
                    name = perm.get("tool_name")
                    if name:
                        targets.add(f"tool:{name}")
        elif settings.get("requires_user_confirmation"):
            name = tool.get("name")
            if name:
                targets.add(f"tool:{_llm_facing_name(name)}")
    return targets


def strip_confirmation_flags(tools: list[dict]) -> list[dict]:
    """Copy the tools with every ``requires_user_confirmation`` flag removed.

    The flag is reconstituted from rules on read; persisting it too would give it
    a second home and let the two drift — the exact bug being closed.
    """
    cleaned = deepcopy(tools)
    for tool in cleaned:
        settings = tool.get("settings")
        if not isinstance(settings, dict):
            continue
        settings.pop("requires_user_confirmation", None)
        for perm in settings.get("allowed_tools") or []:
            if isinstance(perm, dict):
                perm.pop("requires_user_confirmation", None)
    return cleaned


def apply_approval_targets(tools: list[dict], targets: set[str]) -> list[dict]:
    """Copy the tools with the flag set from ``targets`` so the UI round-trips."""
    restored = deepcopy(tools)
    for tool in restored:
        if tool.get("type") == "mcp":
            settings = tool.get("settings")
            if not isinstance(settings, dict):
                continue
            for perm in settings.get("allowed_tools") or []:
                if isinstance(perm, dict) and perm.get("tool_name"):
                    perm["requires_user_confirmation"] = f"tool:{perm['tool_name']}" in targets
        else:
            name = tool.get("name")
            if not name:
                continue
            settings = tool.get("settings")
            if not isinstance(settings, dict):
                settings = {}
                tool["settings"] = settings
            settings["requires_user_confirmation"] = f"tool:{_llm_facing_name(name)}" in targets
    return restored


async def sync_agent_approval_rules(
    session: AsyncSession,
    user_context: UserContext,
    agent_id: UUID,
    targets: set[str],
) -> None:
    """Reconcile an agent's APPROVAL rules to exactly ``targets``.

    Idempotent: existing targets are left alone, missing ones created, and rows
    whose target is no longer ticked are removed.
    """
    repo = PolicyRuleRepository(session, user_context)
    existing = await repo.list_rules(
        subject_type=PolicySubjectType.AGENT,
        subject_id=str(agent_id),
        effect=PolicyEffect.APPROVAL,
    )
    by_target = {rule.target: rule for rule in existing}

    for target in targets:
        rule = by_target.get(target)
        if rule is None:
            await repo.create(
                PolicyRule(
                    subject_type=PolicySubjectType.AGENT,
                    subject_id=str(agent_id),
                    target=target,
                    effect=PolicyEffect.APPROVAL,
                )
            )
        elif not rule.enabled and rule.id is not None:
            await repo.set_enabled(rule.id, True)

    for target, rule in by_target.items():
        if target not in targets and rule.id is not None:
            await repo.delete(rule.id)


async def approval_targets_for_agents(
    session: AsyncSession,
    user_context: UserContext,
    agent_ids: list[UUID],
) -> dict[UUID, set[str]]:
    """The ticked approval targets per agent, for reconstituting the config."""
    wanted = {str(agent_id): agent_id for agent_id in agent_ids}
    repo = PolicyRuleRepository(session, user_context)
    rules = await repo.list_rules(
        subject_type=PolicySubjectType.AGENT,
        effect=PolicyEffect.APPROVAL,
        enabled=True,
    )
    grouped: dict[UUID, set[str]] = {}
    for rule in rules:
        agent_id = wanted.get(rule.subject_id)
        if agent_id is not None:
            grouped.setdefault(agent_id, set()).add(rule.target)
    return grouped
