"""OSS authorization service — user's workspace + system workspace."""

from .authorization import SYSTEM_WORKSPACE_ID, AuthorizationService
from .context import UserContext


class SimpleAuthorizationService(AuthorizationService):
    """OSS implementation of workspace access control.

    Grants read access to the user's own workspace and the system workspace.
    Write access is limited to the user's own workspace.

    Enterprise replaces this with ReBAC-based resolution.
    """

    async def get_accessible_workspaces(self, user_context: UserContext) -> list[str]:
        return [user_context.workspace_id, SYSTEM_WORKSPACE_ID]

    async def can_write_workspace(self, user_context: UserContext, workspace_id: str) -> bool:
        return workspace_id == user_context.workspace_id
