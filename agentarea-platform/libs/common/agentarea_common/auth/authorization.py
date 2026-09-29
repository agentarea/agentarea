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

from .context import UserContext, UserPrincipal

logger = logging.getLogger(__name__)


class AuthorizationService(ABC):
    """Abstract authorization service. OSS and Enterprise provide implementations.

    This service resolves which workspaces a user can access for reads,
    and whether a user can mutate entities in a given workspace.
    """

    @abstractmethod
    async def get_accessible_workspaces(self, principal: UserPrincipal) -> list[str]:
        """Return workspace IDs this principal may act in beyond ownership and membership.

        Ownership and graph membership are resolved by the request dependency;
        this adds whatever an implementation grants on top of them.

        Args:
            principal: The authenticated caller, before any workspace is selected.

        Returns:
            List of additional workspace IDs the principal has access to.
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

    async def can_administer_workspace(self, user_context: UserContext, workspace_id: str) -> bool:
        """Check if the user may change the workspace itself, not just its contents.

        Administering means policy rules, spend limits and access grants —
        authority over what everyone else in the workspace may do. Membership
        does not confer it.

        The default resolves ownership, which is what an implementation without
        its own notion of roles can answer, and it is the only implementation:
        ``WorkspaceScopedAuthorizationService`` had a byte-identical copy until
        2026-09-23, which is two places to keep in step and one to forget. An
        implementation with real roles overrides this; one that has not
        considered the question inherits ownership-only rather than a hole,
        which is why this is concrete rather than abstract.
        """
        if workspace_id == user_context.user_id:
            return True
        return workspace_id in (user_context.admin_workspaces or [])


async def _ensure_admin_workspaces_resolved(user_context: UserContext) -> None:
    """Fill ``admin_workspaces`` for a context minted outside the HTTP boundary.

    ``None`` means nobody has asked yet; ``[]`` means the question was answered
    and this user administers nothing. Without the distinction every non-HTTP
    door -- the MCP bearer path, the worker's code-tool activity -- denied
    silently, which reads as "gated" and is really "never resolved".
    """
    if user_context.admin_workspaces is not None:
        return
    from agentarea_common.workspaces.authority import administered_workspace_ids

    user_context.admin_workspaces = await administered_workspace_ids(user_context.user_id)


async def is_workspace_admin(user_context: UserContext) -> bool:
    """Whether the caller administers the workspace they are acting in."""
    await _ensure_admin_workspaces_resolved(user_context)
    from agentarea_common.di.container import resolve

    authz = resolve(AuthorizationService)
    return await authz.can_administer_workspace(user_context, user_context.workspace_id)


async def assert_workspace_admin(user_context: UserContext) -> None:
    """Raise 403 unless the caller may mutate the given workspace.

    Endpoints that write policy or money — governance policy rules, wallet
    credentials/budgets, the authorization graph — must gate on this.
    Plain workspace membership is not enough: any member could otherwise
    loosen their own spend cap, delete a deny rule, or drain another
    agent's wallet.
    """
    if not await is_workspace_admin(user_context):
        raise HTTPException(
            status_code=403,
            detail="Only a workspace admin may perform this action",
        )


async def assert_workspace_admin_of(user_context: UserContext, workspace_id: str) -> None:
    """Raise 403 unless the caller may administer ``workspace_id``.

    For endpoints that name the workspace in their path -- invitations,
    membership -- where the target need not be the workspace the caller is
    currently acting in. An empty target is refused rather than defaulted.
    """
    from agentarea_common.di.container import resolve

    if not workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required")
    await _ensure_admin_workspaces_resolved(user_context)
    authz = resolve(AuthorizationService)
    if not await authz.can_administer_workspace(user_context, workspace_id):
        raise HTTPException(
            status_code=403,
            detail="Only a workspace admin may perform this action",
        )
