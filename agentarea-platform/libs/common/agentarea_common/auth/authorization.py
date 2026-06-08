"""Authorization service interface for workspace access control.

This module defines the abstract AuthorizationService that determines which
workspaces a user can access. The OSS implementation grants access to the
user's own workspace; built-in/official content is globally readable by
provenance (``source == 'official'``) or via the global registry catalog, not by
membership in a magic 'platform' workspace. Enterprise can replace this with
ReBAC.
"""

import logging
from abc import ABC, abstractmethod

from .context import UserContext

logger = logging.getLogger(__name__)


class AuthorizationService(ABC):
    """Abstract authorization service. OSS and Enterprise provide implementations.

    This service resolves which workspaces a user can access for reads,
    and whether a user can mutate entities in a given workspace.
    """

    @abstractmethod
    async def get_accessible_workspaces(self, user_context: UserContext) -> list[str]:
        """Return the list of workspace IDs this user can read from.

        Args:
            user_context: Current user and workspace context.

        Returns:
            List of workspace IDs the user has read access to.
        """
        ...

    @abstractmethod
    async def can_write_workspace(self, user_context: UserContext, workspace_id: str) -> bool:
        """Check if the user can mutate entities in the given workspace.

        Args:
            user_context: Current user and workspace context.
            workspace_id: The workspace to check write access for.

        Returns:
            True if the user can write to the workspace.
        """
        ...
