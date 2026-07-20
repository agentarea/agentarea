"""Re-export of the approval-rule sync helpers, now homed in the agents lib.

The logic moved to ``agentarea_agents.application.approval_sync`` so every
agent-creation path (router, bundle install, workspace import, catalog fork)
reconciles through ``AgentService``. This module stays as the import site the
router's read-overlay, ``mcp_server_instances``, and the existing tests already
use, so those keep working unchanged.
"""

from agentarea_agents.application.approval_sync import (
    apply_approval_targets,
    approval_targets_for_agents,
    approval_targets_from_tools,
    strip_confirmation_flags,
    sync_agent_approval_rules,
)

__all__ = [
    "apply_approval_targets",
    "approval_targets_for_agents",
    "approval_targets_from_tools",
    "strip_confirmation_flags",
    "sync_agent_approval_rules",
]
