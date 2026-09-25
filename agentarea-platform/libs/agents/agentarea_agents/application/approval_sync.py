"""Translate the agent editor's per-tool "requires approval" toggle into rules.

The toggle used to live in the agent's ``tools`` JSON, where nothing enforced
it. Approval is a governance decision, so it belongs in the policy engine: each
ticked tool becomes an agent-scoped ``PolicyRule(target="tool:<name>",
effect=APPROVAL)``, which the resolver already folds into the snapshot the
workflow gate reads. The toggle's state is the source of truth, so unticking
removes the row rather than disabling it.

The one subtlety is the name. A code toolset is judged by its LLM-facing name,
which collapses the namespace (``agentarea/shell`` -> ``shell``). An MCP tool is
named through the attachment that exposes it, ``mcp:<server ref>:<raw tool>``,
because two attached servers can advertise the same raw name; the runtime offers
that name to the PDP alongside the model-facing one. Rules written earlier under
the bare raw name are still read back, and the next save rewrites them.

This lives in the agents lib (not the API app) so every agent-creation path —
the router, bundle install, workspace import, and catalog fork — reconciles
approval rules through the one home: ``AgentService``.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from agentarea_agents_sdk.tools.mcp_tool_identity import mcp_tool_target
from agentarea_common.auth.context import UserContext
from agentarea_governance.domain.rules import (
    MANAGED_BY_AGENT_TOOLS,
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
)
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession


class ApprovalEnforcedByPolicyError(Exception):
    """An agent edit unticks an approval that a workspace policy rule enforces.

    The toggle only removes rules it wrote. Answering the edit as if it had
    worked leaves the tick coming back on the next read, so it is refused.
    """

    def __init__(self, targets: set[str]) -> None:
        self.targets = targets
        names = ", ".join(sorted(target.removeprefix("tool:") for target in targets))
        super().__init__(
            f"Approval for {names} is enforced by a workspace policy; "
            "change it on the Policies page."
        )


def _llm_facing_name(tool_name: str) -> str:
    """Collapse a code toolset namespace to the name the model actually calls."""
    return tool_name.rsplit("/", 1)[-1]


def _mcp_target(server_ref: str, tool_name: str) -> str:
    return f"tool:{mcp_tool_target(server_ref, tool_name)}"


def approval_targets_from_tools(tools: list[dict]) -> set[str]:
    """Rule targets for every tool the config marks as requiring approval."""
    targets: set[str] = set()
    for tool in tools:
        settings = tool.get("settings") or {}
        if tool.get("type") == "mcp":
            server_ref = tool.get("name")
            for perm in settings.get("allowed_tools") or []:
                if isinstance(perm, dict) and perm.get("requires_user_confirmation"):
                    name = perm.get("tool_name")
                    if name and server_ref:
                        targets.add(_mcp_target(server_ref, name))
        elif settings.get("requires_user_confirmation"):
            name = tool.get("name")
            if name:
                targets.add(f"tool:{_llm_facing_name(name)}")
    return targets


def unticked_targets(tools: list[dict]) -> set[str]:
    """Rule targets of the listed tools that the config leaves without approval."""
    targets: set[str] = set()
    for tool in tools:
        settings = tool.get("settings") or {}
        if tool.get("type") == "mcp":
            server_ref = tool.get("name")
            for perm in settings.get("allowed_tools") or []:
                if not isinstance(perm, dict) or perm.get("requires_user_confirmation"):
                    continue
                name = perm.get("tool_name")
                if name and server_ref:
                    targets.update({_mcp_target(server_ref, name), f"tool:{name}"})
        elif not settings.get("requires_user_confirmation"):
            name = tool.get("name")
            if name:
                targets.add(f"tool:{_llm_facing_name(name)}")
    return targets


async def assert_no_policy_approval_unticked(
    session: AsyncSession,
    user_context: UserContext,
    agent_id: UUID,
    tools: list[dict],
) -> None:
    """Refuse an edit that unticks an approval a policy rule (not the toggle) enforces.

    Raises:
        ApprovalEnforcedByPolicyError: naming the enforced targets.
    """
    rules = await PolicyRuleRepository(session, user_context).list_rules(
        subject_type=PolicySubjectType.AGENT,
        subject_id=str(agent_id),
        effect=PolicyEffect.APPROVAL,
        enabled=True,
    )
    enforced = {rule.target for rule in rules if rule.managed_by is None}
    conflicts = enforced & unticked_targets(tools)
    if conflicts:
        raise ApprovalEnforcedByPolicyError(conflicts)


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


def mcp_tool_ticked(server_ref: str, tool_name: str, targets: set[str]) -> bool:
    """Whether an attached server's tool has an approval rule, old spelling included."""
    return _mcp_target(server_ref, tool_name) in targets or f"tool:{tool_name}" in targets


def apply_approval_targets(tools: list[dict], targets: set[str]) -> list[dict]:
    """Copy the tools with the flag set from ``targets`` so the UI round-trips."""
    restored = deepcopy(tools)
    for tool in restored:
        if tool.get("type") == "mcp":
            settings = tool.get("settings")
            if not isinstance(settings, dict):
                continue
            server_ref = tool.get("name") or ""
            for perm in settings.get("allowed_tools") or []:
                if isinstance(perm, dict) and perm.get("tool_name"):
                    perm["requires_user_confirmation"] = mcp_tool_ticked(
                        server_ref, perm["tool_name"], targets
                    )
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
    """Reconcile the agent's toggle-owned APPROVAL rules to exactly ``targets``.

    Idempotent: existing targets are left alone, missing ones created, and rows
    whose target is no longer ticked are removed. Only rules this sync wrote are
    touched. Anyone who may edit the agent reaches this, admin or not, so a rule
    an admin authored through the policy service is never altered or removed
    here; a target it already requires needs no second rule.
    """
    repo = PolicyRuleRepository(session, user_context)
    existing = await repo.list_rules(
        subject_type=PolicySubjectType.AGENT,
        subject_id=str(agent_id),
        effect=PolicyEffect.APPROVAL,
    )
    owned = {rule.target: rule for rule in existing if rule.managed_by == MANAGED_BY_AGENT_TOOLS}
    authored = {rule.target for rule in existing if rule.managed_by is None and rule.enabled}

    for target in targets:
        rule = owned.get(target)
        if rule is None:
            if target in authored:
                continue
            await repo.create(
                PolicyRule(
                    subject_type=PolicySubjectType.AGENT,
                    subject_id=str(agent_id),
                    target=target,
                    effect=PolicyEffect.APPROVAL,
                    managed_by=MANAGED_BY_AGENT_TOOLS,
                )
            )
        elif not rule.enabled and rule.id is not None:
            await repo.set_enabled(rule.id, True)

    for target, rule in owned.items():
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
