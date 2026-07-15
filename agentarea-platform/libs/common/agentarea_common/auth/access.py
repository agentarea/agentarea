"""The single edge authorization decision point (ADR-006).

Every protocol edge (REST, A2A, MCP, triggers) asks the SAME question here —
"may this subject perform this action on this agent?" — instead of each edge
inventing its own permission model. The engine behind the decision is
pluggable: today it is workspace scope plus a hook for a data-driven public
grant; ReBAC/policy can be wired in without touching any call site.

This is edge *admission* ("may you invoke"). It composes with, and does not
replace, ADR-005's in-execution governance ("what may the run do").
"""

import logging
from dataclasses import dataclass

from .context import UserContext

logger = logging.getLogger(__name__)

# Action verbs (stable inputs to the decision, not a permission table).
AGENT_READ = "agent:read"
AGENT_WRITE = "agent:write"
AGENT_EXECUTE = "agent:execute"
AGENT_STREAM = "agent:stream"


@dataclass(frozen=True)
class EdgeDecision:
    """Result of an edge authorization decision."""

    allowed: bool
    reason: str = ""


async def _has_public_grant(agent_id: str, action: str) -> bool:
    """Whether the agent grants this action to everyone (anonymous included).

    Data-driven hook. When the ReBAC model for agents lands this consults a
    tuple like ``agent:<id>#executor@everyone`` (or an equivalent policy flag).
    Until then there are no public grants, so this is False — public execution
    is expressible here as data, never as a hardcoded permission list.
    """
    return False


async def authorize_agent_action(
    subject: UserContext | None,
    action: str,
    *,
    agent_workspace_id: str,
    agent_id: str,
) -> EdgeDecision:
    """Decide whether ``subject`` may perform ``action`` on the agent.

    The one place edge policy is evaluated. Order:
      1. Public grant (data) → allow anyone, keyless included.
      2. Anonymous with no public grant → deny.
      3. Authenticated subject within the agent's workspace (scope) → allow.
      4. Otherwise deny (per-principal ReBAC grants plug in here later).
    """
    if await _has_public_grant(agent_id, action):
        return EdgeDecision(True, "public grant")

    if subject is None:
        return EdgeDecision(False, "anonymous subject and no public grant")

    accessible = subject.accessible_workspaces or [subject.workspace_id]
    if agent_workspace_id in accessible:
        return EdgeDecision(True, "workspace scope")

    return EdgeDecision(
        False,
        f"subject {subject.user_id} not in agent workspace {agent_workspace_id}",
    )
