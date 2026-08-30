"""Authorization service interface for workspace access control.

This module defines the abstract AuthorizationService that determines which
workspaces a user can access. The OSS implementation grants access to the
user's own workspace; built-in/official content lives in the global registry
catalog and is read globally by the catalog repositories, not by membership in a
magic 'platform' workspace. Enterprise can replace this with ReBAC.
"""

import logging
from abc import ABC, abstractmethod

from fastapi import HTTPException

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


async def assert_workspace_admin(user_context: UserContext) -> None:
    """Raise 403 unless the caller may mutate the given workspace.

    Endpoints that write policy or money — governance policy rules, wallet
    credentials/budgets, the authorization graph — must gate on this.
    Plain workspace membership is not enough: any member could otherwise
    loosen their own spend cap, delete a deny rule, or drain another
    agent's wallet.
    """
    from agentarea_common.di.container import resolve

    authz = resolve(AuthorizationService)
    if not await authz.can_write_workspace(user_context, user_context.workspace_id):
        raise HTTPException(
            status_code=403,
            detail="Only a workspace admin may perform this action",
        )
