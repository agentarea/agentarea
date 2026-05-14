"""AgentArea Workspaces Library.

Workspace-level configuration: budget caps and other settings that don't
fit on individual workspace-scoped resources.
"""

__version__ = "0.0.1"

from agentarea_workspaces.domain.models import WorkspaceSettings
from agentarea_workspaces.infrastructure.repository import WorkspaceSettingsRepository

__all__ = [
    "WorkspaceSettings",
    "WorkspaceSettingsRepository",
]
