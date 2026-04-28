"""OSS authorization service — pure policy, no infrastructure access."""

from .authorization import SYSTEM_WORKSPACE_ID, AuthorizationService
from .context import UserContext


class SimpleAuthorizationService(AuthorizationService):
    """OSS implementation of workspace access control.

    Pure policy: own workspace + system workspace.

    Workspace memberships (added by accepting invitations) are resolved by
    the request-scoped dependency in ``auth.dependencies``, not here, so
    this service stays free of infrastructure dependencies and can run as
    a singleton without leaking SQL sessions across requests.

    Enterprise replaces this with ReBAC-based resolution.
    """

    async def get_accessible_workspaces(self, user_context: UserContext) -> list[str]:
        return [user_context.workspace_id, SYSTEM_WORKSPACE_ID]

    async def can_write_workspace(self, user_context: UserContext, workspace_id: str) -> bool:
        return workspace_id == user_context.workspace_id
